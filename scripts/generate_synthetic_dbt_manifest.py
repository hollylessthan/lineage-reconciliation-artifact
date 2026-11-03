#!/usr/bin/env python3
"""Generate source-free, schema-valid dbt manifests for lineage ingestion replay.

The source SQL is entirely synthetic. Only node identifiers and dependency
graphs are carried from the curated experimental index.
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "evidence/compiler/zero-manifests/index.json"

def build(case, destination):
    target = case["node"]["unique_id"]
    parts = target.split(".")
    if len(parts) != 3 or parts[0] != "model":
        raise ValueError("This fixture generator only supports dbt model targets")
    project = parts[1]
    nodes = sorted(set(case["before_deps"]) | set(case["after_deps"]) | {target})
    name_map = {}
    for item in nodes:
        p = item.split(".")
        if len(p) != 3 or p[0] != "model" or p[1] != project:
            raise ValueError("Unsupported cross-package or source dependency: " + item)
        name_map[item] = p[2]
    for side in ("before", "after"):
        work = destination / ("build-" + side)
        models = work / "models"
        models.mkdir(parents=True, exist_ok=True)
        (work / "dbt_project.yml").write_text(
            "name: " + json.dumps(project) + "\nversion: '1.0'\n"
            "config-version: 2\nprofile: synthetic\n"
            "model-paths: ['models']\n"
            "models:\n  " + project + ":\n    +materialized: view\n")
        (work / "profiles.yml").write_text(
            'synthetic:\n  target: dev\n  outputs:\n    dev:\n'
            '      type: postgres\n      host: 127.0.0.1\n      port: 5432\n'
            '      user: synthetic\n      password: synthetic\n'
            '      dbname: synthetic\n      schema: main\n      threads: 1\n')
        active = set(case["before_deps"] if side == "before" else case["after_deps"])
        for uid,name in name_map.items():
            if uid == target and active:
                expr = " union all ".join("select id from {{ ref(" + json.dumps(name_map[d]) + ") }}" for d in sorted(active))
            else:
                expr = "select 1 as id"
            (models / (name + ".sql")).write_text(expr + "\n")
        cmd = ["dbt","parse","--project-dir",str(work),"--profiles-dir",str(work),"--no-partial-parse","--quiet"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode:
            raise RuntimeError(f"dbt parse failed for {side}: {proc.stderr[-1800:]} {proc.stdout[-1800:]}")
        doc = json.loads((work / "target/manifest.json").read_text())
        actual = doc["nodes"][target]["depends_on"]["nodes"]
        if sorted(actual) != sorted(active):
            raise ValueError(f"Dependencies changed for {side}: {actual} != {sorted(active)}")
        output = destination / case["id"] / side
        output.mkdir(parents=True, exist_ok=True)
        (output / "manifest.json").write_text(json.dumps(doc, sort_keys=True))
    (destination / "index.json").write_text(json.dumps([case],indent=2))
    print("PASS: generated complete dbt manifests from synthetic SQL for " + case["id"])

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--case",default="zero01")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    case=next(x for x in json.loads(INDEX.read_text()) if x["id"]==args.case)
    if case["id"] not in {"zero01","zero03","zero04","zero05"}:
        parser.error("Only source-minimized third-party cases are supported")
    build(case,args.output)

if __name__=="__main__":
    main()
