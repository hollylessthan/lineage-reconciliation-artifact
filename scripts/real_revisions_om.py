"""Replay compiled real revision pairs through native OpenMetadata dbt ingestion.

Same design as real_revisions.py (DataHub): for each accepted pair, histories
[before, after] and [after, before] run in separate database services, and MR1 is checked
on the changed model's observed upstream tables:
  forward:  S([before, after]) == S([after])
  reverse:  S([after, before]) == S([before])
A sanity check compares each fresh state with the compiled depends_on set.

OpenMetadata's dbt source links dbt nodes to existing table entities by database, schema
and name. Each manifest copy is therefore rebound to a disposable CustomDatabase service
(database `fixture`, schema `main`); node identities, aliases and depends_on are unchanged.
The model and every node it depends on in either revision are registered as tables first.
Probe after protocol-v1; not part of the frozen measurement.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pilot import run, save  # noqa: E402


class OM:
    def __init__(self, server):
        self.server = server

    def api(self, method, path, body=None, ok404=False):
        r = requests.request(method, self.server + '/api/v1' + path, json=body, timeout=60)
        if ok404 and r.status_code == 404:
            return None
        if r.status_code >= 300:
            raise RuntimeError(f'{method} {path}: {r.status_code} {r.text[:400]}')
        return r.json() if r.content else None


def table_name(n):
    return (n.get('alias') or n.get('identifier') or n['name']).lower()


def rebind(manifest):
    m = copy.deepcopy(manifest)
    for group in ('nodes', 'sources'):
        for n in m.get(group, {}).values():
            n['database'], n['schema'] = 'fixture', 'main'
            if 'relation_name' in n:
                n['relation_name'] = f'"fixture"."main"."{table_name(n)}"'
    return m


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifests', type=Path, required=True)
    p.add_argument('--server', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--override', action='store_true', help='overrideLineage=true (Replace contract)')
    a = p.parse_args()
    om = OM(a.server)
    out = a.output.resolve()
    index = json.loads((a.manifests / 'index.json').read_text())
    results = []
    for case in index:
        if case['status'] != 'accepted':
            continue
        manifests = {s: json.loads((a.manifests / case['id'] / s / 'manifest.json').read_text()) for s in ('before', 'after')}
        node = case['node']['unique_id']
        lookup = {**manifests['before']['nodes'], **manifests['before'].get('sources', {}),
                  **manifests['after']['nodes'], **manifests['after'].get('sources', {})}
        involved = sorted({node, *case['before_deps'], *case['after_deps']})
        names = {x: table_name(lookup[x]) for x in involved}
        expect = {'before': sorted(names[x] for x in case['before_deps']),
                  'after': sorted(names[x] for x in case['after_deps'])}
        states = {}
        for hist in (('before', 'after'), ('after', 'before')):
            svc = 'rr' + hashlib.sha1((case['id'] + '/'.join(hist) + str(a.override)).encode()).hexdigest()[:8]
            d = out / case['id'] / '-'.join(hist)
            om.api('POST', '/services/databaseServices', {'name': svc, 'serviceType': 'CustomDatabase',
                   'connection': {'config': {'type': 'CustomDatabase'}}})
            om.api('POST', '/databases', {'name': 'fixture', 'service': svc})
            om.api('POST', '/databaseSchemas', {'name': 'main', 'database': f'{svc}.fixture'})
            ents = {}
            for x in involved:
                if names[x] not in ents:
                    ents[names[x]] = om.api('POST', '/tables', {'name': names[x], 'databaseSchema': f'{svc}.fixture.main',
                                                                'columns': [{'name': 'id', 'dataType': 'INT'}]})
            save(d / 'registered-entities.json', ents)
            target = ents[names[node]]
            by_id = {e['id']: n for n, e in ents.items()}
            ok = True
            for i, side in enumerate(hist):
                mpath = d / f'step{i}' / 'manifest.json'
                save(mpath, rebind(manifests[side]))
                cfg = {'type': 'DBT', 'dbtConfigSource': {'dbtConfigType': 'local', 'dbtManifestFilePath': str(mpath)}}
                if a.override:
                    cfg['overrideLineage'] = True
                recipe = {'source': {'type': 'dbt', 'serviceName': svc, 'sourceConfig': {'config': cfg}},
                          'sink': {'type': 'metadata-rest', 'config': {}},
                          'workflowConfig': {'loggerLevel': 'INFO', 'openMetadataServerConfig': {
                              'hostPort': a.server + '/api', 'authProvider': 'openmetadata',
                              'securityConfig': {'jwtToken': 'disposable-no-auth'}}}}
                save(d / f'step{i}' / 'recipe.json', recipe)
                code = run(['metadata', 'ingest', '-c', str(d / f'step{i}' / 'recipe.json')], d / f'step{i}' / 'ingest.log', timeout=600)
                ok = ok and code == 0
                samples = []
                for _ in range(3):
                    lin = om.api('GET', f"/lineage/table/{target['id']}?upstreamDepth=1&downstreamDepth=0")
                    samples.append(sorted(by_id.get(e['fromEntity'], 'unregistered:' + e['fromEntity'])
                                          for e in (lin.get('upstreamEdges') or []) if e['toEntity'] == target['id']))
                    time.sleep(1)
                save(d / f'step{i}' / 'observations.json', {'samples': samples, 'exit_code': code})
                states[hist[:i + 1]] = tuple(samples[-1]) if ok and samples[0] == samples[-1] else None

        def check(x, y):
            if states.get(x) is None or states.get(y) is None:
                return 'not_testable'
            return 'holds' if states[x] == states[y] else 'violation'

        row = {'id': case['id'], 'repository': case['repository'], 'commit': case['commit'], 'path': case['path'],
               'override': a.override, 'removed': case['removed'], 'added': case['added'],
               'sanity_before': list(states.get(('before',)) or ()) == expect['before'] and states.get(('before',)) is not None,
               'sanity_after': states.get(('after',)) is not None and list(states[('after',)]) == expect['after'],
               'MR1_forward': check(('before', 'after'), ('after',)),
               'MR1_reverse': check(('after', 'before'), ('before',)),
               'states': {'/'.join(k): list(v) if v is not None else None for k, v in states.items()},
               'expected': expect}
        results.append(row)
        save(out / 'real-revision-results.json', results)
        print('MMREALOM ' + json.dumps(row), flush=True)
    save(out / 'real-revision-results.json', results)


if __name__ == '__main__':
    main()
