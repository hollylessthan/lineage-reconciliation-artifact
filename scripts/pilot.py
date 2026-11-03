"""Small native DataHub/dbt capability pilot. No catalog semantics are emulated."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
MODEL_NAMES = ("a", "b", "c", "out")
CASE_ENVS = ("DEV", "TEST", "QA", "UAT", "STG", "SBX")


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def run(args, log, *, timeout=180):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as f:
        p = subprocess.run(args, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                           timeout=timeout, env={**os.environ, "DO_NOT_TRACK": "1"})
    return p.returncode


def expected(revision):
    # Authored independently of the native extractor and the observation parser.
    return {tuple(e) for e in json.loads((ROOT / "fixtures/expected.json").read_text())[revision]}


def score(observed, wanted):
    return {"exact": observed == wanted,
            "missing": sorted(wanted - observed), "extra": sorted(observed - wanted)}


def closure(edges, root, *, downstream):
    found, pending = set(), [root]
    while pending:
        node = pending.pop()
        for source, target in edges:
            start, end = (source, target) if downstream else (target, source)
            if start == node and end != root and end not in found:
                found.add(end)
                pending.append(end)
    return sorted(found)


def build_fixtures(out):
    manifests = {}
    sql = {
        "r0": "select * from {{ ref('a') }} union all select * from {{ ref('b') }}\n",
        "r1": "select * from {{ ref('a') }} union all select * from {{ ref('c') }}\n",
        "empty": "select 42 as id\n",
    }
    for rev, text in sql.items():
        project = out / "projects" / rev
        shutil.copytree(ROOT / "fixtures", project, dirs_exist_ok=True)
        (project / "models/out.sql").write_text(text)
        command = ["dbt", "parse", "--no-partial-parse", "--project-dir", str(project),
                   "--profiles-dir", str(project)]
        if run(command, out / "logs" / f"dbt-{rev}.log"):
            raise RuntimeError(f"dbt parse failed for {rev}; inspect logs")
        manifest = project / "target/manifest.json"
        data = json.loads(manifest.read_text())
        edges = set()
        for node in data["nodes"].values():
            if node["resource_type"] == "model":
                for dep in node["depends_on"]["nodes"]:
                    if dep.startswith("model."):
                        edges.add((data["nodes"][dep]["name"], node["name"]))
        if edges != expected(rev):
            raise RuntimeError(f"Fixture {rev} contradicts hand-authored expected edges")
        manifests[rev] = manifest
    # Explicit artifact fault, not a real source revision: hide the out model.
    partial = json.loads(manifests["r1"].read_text())
    key = "model.reconciliation_fixture.out"
    partial["nodes"].pop(key)
    for map_name in ("parent_map", "child_map"):
        partial[map_name].pop(key, None)
        for value in partial[map_name].values():
            if key in value:
                value.remove(key)
    partial_path = out / "projects/omitted/manifest.json"
    save(partial_path, partial)
    manifests["omitted"] = partial_path
    missing = out / "projects/missing/manifest.json"
    manifests["missing"] = missing  # Deliberately absent, never replace with {}.
    return manifests


def config(manifest, env, mode, sink):
    source = {"manifest_path": str(manifest), "target_platform": "duckdb", "env": env,
              "include_column_lineage": False, "infer_dbt_schemas": False,
              "stateful_ingestion": {"enabled": False}}
    if mode in ("override", "combined"):
        source["write_semantics"] = "OVERRIDE"
    if mode in ("nonincremental", "combined"):
        source["incremental_lineage"] = False
    if mode in ("stateful", "combined"):
        source["stateful_ingestion"] = {"enabled": True, "remove_stale_metadata": True}
    # default mode leaves incremental_lineage unspecified, exercising native default.
    return {"pipeline_name": f"pilot-{env}", "source": {"type": "dbt", "config": source},
            "sink": sink}


def ingest(manifest, env, mode, directory, server=None):
    if server:
        sink = {"type": "datahub-rest", "config": {"server": server, "mode": "SYNC"}}
    else:
        sink = {"type": "file", "config": {"filename": str(directory / "events.json")}}
    directory.mkdir(parents=True, exist_ok=True)
    recipe = directory / "recipe.json"
    save(recipe, config(manifest, env, mode, sink))
    code = run(["datahub", "ingest", "-c", str(recipe)], directory / "ingest.log", timeout=240)
    save(directory / "execution.json", {"exit_code": code, "live_sink": bool(server)})
    return code


def snapshot(graph, env):
    from datahub.metadata.schema_classes import StatusClass, UpstreamLineageClass
    edges, raw = set(), {}
    names = {f"urn:li:dataset:(urn:li:dataPlatform:dbt,fixture.main.{n},{env})": n
             for n in MODEL_NAMES}
    # Native dbt output points to physical upstream tables; map these exact
    # fixture identities without collapsing arbitrary sibling relationships.
    upstream_names = {f"urn:li:dataset:(urn:li:dataPlatform:{platform},fixture.main.{n},{env})": n
                      for n in MODEL_NAMES for platform in ("dbt", "duckdb")}
    for urn, name in names.items():
        status = graph.get_aspect(urn, StatusClass)
        if status is None or status.removed:
            raise RuntimeError(f"Fixture entity is missing or removed: {urn}")
        aspect = graph.get_aspect(urn, UpstreamLineageClass)
        raw[urn] = {"status": status.to_obj(),
                    "upstreamLineage": aspect.to_obj() if aspect else None}
        if aspect:
            for upstream in aspect.upstreams:
                if upstream.dataset not in upstream_names:
                    raise RuntimeError(f"Unexpected fixture upstream identity: {upstream.dataset}")
                edges.add((upstream_names[upstream.dataset], name))
    return edges, raw


def interrupt_ingest(manifest, env, mode, directory, server):
    """Block the out-lineage request, then kill only this ingestion child."""
    import requests
    directory.mkdir(parents=True, exist_ok=True)
    reached, release = threading.Event(), threading.Event()
    writes = []
    target = f"urn:li:dataset:(urn:li:dataPlatform:dbt,fixture.main.out,{env})"

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def forward(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.command == "POST" and target.encode() in body and b"upstreamLineage" in body:
                reached.set()
                release.wait(30)
                self.send_response(503)
                self.end_headers()
                return
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in ("host", "connection", "content-length")}
            response = requests.request(self.command, server + self.path, data=body,
                                        headers=headers, timeout=30)
            if self.command == "POST" and b'"changeType"' in body:
                writes.append({"path": self.path, "status": response.status_code,
                               "request_sha256": hashlib.sha256(body).hexdigest()})
            self.send_response(response.status_code)
            self.send_header("Content-Length", str(len(response.content)))
            self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = forward

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    proxy.daemon_threads = True
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    recipe = directory / "recipe.json"
    save(recipe, config(manifest, env, mode, {"type": "datahub-rest", "config": {
        "server": f"http://127.0.0.1:{proxy.server_port}", "mode": "SYNC"}}))
    try:
        with (directory / "ingest.log").open("w") as f:
            proc = subprocess.Popen(["datahub", "ingest", "-c", str(recipe)],
                                    stdout=f, stderr=subprocess.STDOUT, cwd=ROOT)
            try:
                if not reached.wait(90):
                    raise RuntimeError("Interruption target was not reached")
                proc.kill()
                proc.wait(timeout=10)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=10)
        if not any(200 <= w["status"] < 300 for w in writes):
            raise RuntimeError("Interruption occurred before any successful metadata writes")
        save(directory / "interruption.json", {"target_blocked": True,
             "child_return_code": proc.returncode, "forwarded_writes": writes})
        return proc.returncode
    finally:
        release.set()
        proxy.shutdown()
        proxy.server_close()


def observe(graph, env, wanted, directory, seconds=30):
    start, samples = time.monotonic(), []
    # A sustained exact result is a convergence observation, not a linearizability claim.
    stable = 0
    while True:
        edges, raw = snapshot(graph, env)
        samples.append({"elapsed_seconds": round(time.monotonic()-start, 3),
                        "edges": sorted(edges), "aspects": raw})
        stable = stable + 1 if edges == wanted else 0
        if stable >= 3 or time.monotonic()-start >= seconds:
            break
        time.sleep(1)
    save(directory / "observations.json", samples)
    queries = [{"root": n, "direction": direction,
                "observed": closure(edges, n, downstream=direction == "downstream"),
                "expected": closure(wanted, n, downstream=direction == "downstream")}
               for n in MODEL_NAMES for direction in ("upstream", "downstream")]
    return {**score(edges, wanted), "observed_edges": sorted(edges),
            "stable_exact": stable >= 3, "elapsed_seconds": samples[-1]["elapsed_seconds"],
            "query_matches": sum(q["observed"] == q["expected"] for q in queries),
            "query_total": len(queries), "queries": queries}


def live(out, manifests, server):
    from datahub.ingestion.graph.client import DataHubGraph
    from datahub.ingestion.graph.config import DatahubClientConfig
    graph = DataHubGraph(DatahubClientConfig(server=server))
    cases = [("replacement", "r1"), ("last_dependency_removed", "empty"),
             ("explicit_missing_manifest", "missing"), ("unreported_omission", "omitted"),
             ("stale_artifact_replay", "r0"), ("interrupted_delivery", "r1")]
    results = []
    # Single native configuration for stage 1; do not manufacture a config contrast.
    for mode in ("default",):
        for idx, (case, revision) in enumerate(cases):
            # Isolated environments, no destructive reset of the catalog.
            env = CASE_ENVS[idx]  # Native FabricType enum; fresh server is mandatory.
            directory = out / "live" / mode / case
            directory.mkdir(parents=True, exist_ok=True)
            if any(graph.exists(f"urn:li:dataset:(urn:li:dataPlatform:dbt,fixture.main.{n},{env})")
                   for n in MODEL_NAMES):
                raise RuntimeError("Pilot environment already exists; use a fresh disposable server")
            if ingest(manifests["r0"], env, mode, directory / "initial", server):
                raise RuntimeError(f"Initial ingestion failed: {directory}")
            initial = observe(graph, env, expected("r0"), directory / "initial")
            if not initial["stable_exact"]:
                raise RuntimeError(f"Initial graph is not correct: {directory}")
            if case == "stale_artifact_replay":
                if ingest(manifests["r1"], env, mode, directory / "advance", server):
                    raise RuntimeError("Cannot establish new revision before old-artifact replay")
                advanced = observe(graph, env, expected("r1"), directory / "advance")
                if not advanced["stable_exact"]:
                    raise RuntimeError("New revision did not converge before replay")
            exit_code = (interrupt_ingest(manifests[revision], env, mode, directory / "changed", server)
                         if case == "interrupted_delivery" else
                         ingest(manifests[revision], env, mode, directory / "changed", server))
            # Failed missing-manifest delivery should preserve prior graph. Omission is
            # explicitly unreported; the application target differs from what consumer knows.
            wanted = expected("r0" if revision == "missing" or case == "interrupted_delivery" else
                              "r1" if revision in ("omitted", "r0") else revision)
            changed = observe(graph, env, wanted, directory / "changed", seconds=12)
            recovery_rev = "empty" if revision == "empty" else "r1"
            recovery_code = ingest(manifests[recovery_rev], env, mode, directory / "recovery", server)
            recovery = observe(graph, env, expected(recovery_rev), directory / "recovery", seconds=12)
            results.append({"case": case, "mode": mode, "environment": env,
                            "changed_exit_code": exit_code, "changed": changed,
                            "recovery_exit_code": recovery_code, "recovery": recovery,
                            "classification": "underdetermined_input" if revision == "omitted" else
                            "arrival_order_diagnostic" if case == "stale_artifact_replay" else
                            "contract_review_required"})
            save(out / "live-results.json", results)
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--server")
    args = p.parse_args()
    if args.server and (urlparse(args.server).hostname not in ("127.0.0.1", "localhost")
                        or urlparse(args.server).scheme != "http"):
        p.error("Pilot supports only disposable loopback HTTP servers")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifests = build_fixtures(out)
    metadata = {"python": sys.version, "packages": {n: importlib.metadata.version(n)
                for n in ("acryl-datahub", "dbt-core", "dbt-duckdb", "duckdb")},
                "manifest_sha256": {r: hashlib.sha256(f.read_bytes()).hexdigest()
                                    for r, f in manifests.items() if f.exists()},
                "server": args.server, "github_sha": os.environ.get("GITHUB_SHA")}
    save(out / "execution-identity.json", metadata)
    # Default PATCH requires a live graph; never substitute a fake empty graph.
    for mode in (("default", "override") if args.server else ("override",)):
        for rev in ("r0", "r1", "empty"):
            directory = out / "emissions" / mode / rev
            if args.server:
                sink = {"type": "file", "config": {"filename": str(directory / "events.json")}}
                recipe = config(manifests[rev], "DEV", mode, sink)
                recipe["datahub_api"] = {"server": args.server}
                save(directory / "recipe.json", recipe)
                code = run(["datahub", "ingest", "-c", str(directory / "recipe.json")],
                           directory / "ingest.log", timeout=240)
            else:
                code = ingest(manifests[rev], "DEV", mode, directory)
            if code:
                raise RuntimeError(f"Offline native extraction failed: {mode}/{rev}")
    if args.server:
        live(out, manifests, args.server)
    else:
        save(out / "status.json", {"status": "native_emission_only", "live_catalog_tested": False})


if __name__ == "__main__":
    main()
