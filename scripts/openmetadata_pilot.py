"""Native OpenMetadata dbt ingestion over registered fixture table identities.

Entity registration is setup only; every measured lineage update is from the
unmodified native dbt connector. The explicit delete is a separate control.
"""
import argparse
import hashlib
import importlib.metadata
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, quote
import subprocess

import requests
from pilot import build_fixtures, expected, score, closure, save, run, MODEL_NAMES, ROOT


def api(server, method, path, body=None):
    r = requests.request(method, server + '/api/v1' + path, json=body, timeout=45)
    r.raise_for_status()
    return r.json() if r.content else None


def setup(server, service, directory):
    # Fail rather than silently reuse a previous run's graph.
    response = requests.get(server + '/api/v1/services/databaseServices/name/' + service, timeout=30)
    if response.status_code != 404:
        raise RuntimeError(f'Expected absent fixture service; got {response.status_code}')
    api(server, 'POST', '/services/databaseServices', {'name': service, 'serviceType': 'CustomDatabase',
        'connection': {'config': {'type': 'CustomDatabase'}}})
    api(server, 'POST', '/databases', {'name': 'fixture', 'service': service})
    api(server, 'POST', '/databaseSchemas', {'name': 'main', 'database': service + '.fixture'})
    entities = {}
    for name in MODEL_NAMES:
        entities[name] = api(server, 'POST', '/tables', {'name': name,
            'databaseSchema': service + '.fixture.main',
            'columns': [{'name': 'id', 'dataType': 'INT'}]})
    save(directory / 'registered-entities.json', entities)
    return entities


def snapshot(server, entities):
    raw, edges = {}, set()
    ids = {entity['id']: name for name, entity in entities.items()}
    for name, entity in entities.items():
        current = api(server, 'GET', '/tables/' + entity['id'])
        if current.get('deleted') or current['id'] != entity['id']:
            raise RuntimeError('Missing, removed, or mismatched fixture entity')
        lineage = api(server, 'GET', '/lineage/table/' + entity['id'] + '?upstreamDepth=1&downstreamDepth=0')
        if lineage['entity']['id'] != entity['id'] or 'upstreamEdges' not in lineage:
            raise RuntimeError('Unexpected native lineage response')
        raw[name] = {'table': current, 'lineage': lineage}
        for edge in lineage['upstreamEdges'] or []:
            source, target = edge['fromEntity'], edge['toEntity']
            if source not in ids or target not in ids or target != entity['id']:
                raise RuntimeError('Unknown or unexpected native lineage endpoint')
            edges.add((ids[source], ids[target]))
    return edges, raw


def observe(server, entities, wanted, directory, seconds=60):
    start, samples, stable = time.monotonic(), [], 0
    while True:
        edges, raw = snapshot(server, entities)
        samples.append({'elapsed_seconds': round(time.monotonic()-start, 3),
                        'edges': sorted(edges), 'raw': raw})
        stable = stable + 1 if edges == wanted else 0
        if stable >= 3 or time.monotonic()-start >= seconds:
            break
        time.sleep(1)
    save(directory / 'observations.json', samples)
    queries = [{'root': n, 'direction': direction,
                'observed': closure(edges, n, downstream=direction == 'downstream'),
                'expected': closure(wanted, n, downstream=direction == 'downstream')}
               for n in MODEL_NAMES for direction in ('upstream', 'downstream')]
    return {**score(edges, wanted), 'observed_edges': sorted(edges), 'stable_exact': stable >= 3,
            'elapsed_seconds': samples[-1]['elapsed_seconds'], 'queries': queries,
            'query_matches': sum(q['observed'] == q['expected'] for q in queries), 'query_total': 8}


def recipe(manifest, service, mode, server):
    config = {'type': 'DBT', 'dbtConfigSource': {'dbtConfigType': 'local',
              'dbtManifestFilePath': str(manifest)}}
    if mode == 'override':
        config['overrideLineage'] = True
    return {'source': {'type': 'dbt', 'serviceName': service, 'sourceConfig': {'config': config}},
            'sink': {'type': 'metadata-rest', 'config': {}},
            'workflowConfig': {'loggerLevel': 'INFO', 'openMetadataServerConfig': {
                'hostPort': server + '/api', 'authProvider': 'openmetadata',
                'securityConfig': {'jwtToken': 'disposable-no-auth'}}}}


def ingest(manifest, service, mode, directory, server):
    save(directory / 'recipe.json', recipe(manifest, service, mode, server))
    code = run(['metadata', 'ingest', '-c', str(directory / 'recipe.json')],
               directory / 'ingest.log', timeout=240)
    save(directory / 'execution.json', {'exit_code': code})
    return code


def interrupted(manifest, service, mode, directory, server, target):
    reached, release = threading.Event(), threading.Event()
    writes = []
    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def forward(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            if self.command == 'PUT' and '/lineage' in self.path and target.encode() in body:
                reached.set()
                release.wait(30)
                self.send_response(503)
                self.end_headers()
                return
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in ('host', 'connection', 'content-length')}
            r = requests.request(self.command, server + self.path, data=body, headers=headers, timeout=45)
            if self.command in ('POST', 'PUT', 'PATCH', 'DELETE'):
                writes.append({'method': self.command, 'path': self.path,
                               'status': r.status_code, 'request_sha256': hashlib.sha256(body).hexdigest()})
            self.send_response(r.status_code)
            self.send_header('Content-Length', str(len(r.content)))
            self.send_header('Content-Type', r.headers.get('Content-Type', 'application/json'))
            self.end_headers()
            self.wfile.write(r.content)
        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = forward
    proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    proxy.daemon_threads = True
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    save(directory / 'recipe.json', recipe(manifest, service, mode, f'http://127.0.0.1:{proxy.server_port}'))
    try:
        with (directory / 'ingest.log').open('w') as log:
            proc = subprocess.Popen(['metadata', 'ingest', '-c', str(directory / 'recipe.json')],
                                    stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
            try:
                if not reached.wait(120):
                    raise RuntimeError('Native lineage cut point not reached')
                proc.kill()
                proc.wait(timeout=10)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=10)
        if not any(200 <= w['status'] < 300 for w in writes):
            raise RuntimeError('No acknowledged metadata writes before interruption')
        save(directory / 'interruption.json', {'target_blocked': True,
             'child_return_code': proc.returncode, 'forwarded_writes': writes})
        return proc.returncode
    finally:
        release.set()
        proxy.shutdown()
        proxy.server_close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--server', required=True)
    args = p.parse_args()
    if urlparse(args.server).hostname not in ('127.0.0.1', 'localhost') or urlparse(args.server).scheme != 'http':
        p.error('Disposable loopback HTTP server required')
    out = args.output.resolve()
    manifests = build_fixtures(out)
    save(out / 'execution-identity.json', {'github_sha': os.environ.get('GITHUB_SHA'),
         'client': importlib.metadata.version('openmetadata-ingestion'),
         'manifest_sha256': {r: hashlib.sha256(f.read_bytes()).hexdigest()
                             for r, f in manifests.items() if f.exists()}})
    cases = [('replacement', 'r1'), ('last_dependency_removed', 'empty'),
             ('explicit_missing_manifest', 'missing'), ('unreported_omission', 'omitted'),
             ('stale_artifact_replay', 'r0'), ('interrupted_delivery', 'r1')]
    results = []
    for mode in ('default', 'override'):
        for idx, (case, revision) in enumerate(cases):
            service = f'pilot_{mode}_{idx}'
            d = out / mode / case
            entities = setup(args.server, service, d)
            if ingest(manifests['r0'], service, mode, d / 'initial', args.server):
                raise RuntimeError('Initial native ingestion failed')
            initial = observe(args.server, entities, expected('r0'), d / 'initial')
            if not initial['stable_exact']:
                raise RuntimeError('Cannot establish correct initial graph')
            if case == 'stale_artifact_replay':
                if ingest(manifests['r1'], service, mode, d / 'advance', args.server):
                    raise RuntimeError('Advance failed')
                if not observe(args.server, entities, expected('r1'), d / 'advance')['stable_exact']:
                    # Default additive lineage may retain b. That is an observed configuration
                    # result, and does not establish a correct state for a stale-replay test.
                    save(d / 'not-established.json', {'reason': 'r1 did not converge; stale replay is confounded'})
                    results.append({'mode': mode, 'case': case, 'not_established': True})
                    save(out / 'native-results.json', results)
                    continue
            code = (interrupted(manifests[revision], service, mode, d / 'changed', args.server,
                                entities['out']['id']) if case == 'interrupted_delivery' else
                    ingest(manifests[revision], service, mode, d / 'changed', args.server))
            wanted = expected('r0' if revision == 'missing' or case == 'interrupted_delivery' else
                              'r1' if revision in ('omitted', 'r0') else revision)
            changed = observe(args.server, entities, wanted, d / 'changed')
            recovery_revision = 'empty' if revision == 'empty' else 'r1'
            recovery_code = ingest(manifests[recovery_revision], service, mode, d / 'recovery', args.server)
            recovery = observe(args.server, entities, expected(recovery_revision), d / 'recovery')
            row = {'mode': mode, 'case': case, 'changed_exit_code': code, 'changed': changed,
                   'recovery_exit_code': recovery_code, 'recovery': recovery}
            if revision == 'empty':
                # Native API intervention only after both native empty ingestions are measured.
                path = '/lineage/table/' + entities['out']['id'] + '/type/DbtLineage'
                save(d / 'explicit_clear' / 'request.json', {'method': 'DELETE', 'path': path})
                api(args.server, 'DELETE', path)
                row['explicit_clear'] = observe(args.server, entities, set(), d / 'explicit_clear')
                if not row['explicit_clear']['stable_exact']:
                    raise RuntimeError('Explicit source-lineage removal control failed')
            results.append(row)
            save(out / 'native-results.json', results)


if __name__ == '__main__':
    main()
