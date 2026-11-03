"""Replay compiler-validated real revision pairs through native DataHub dbt ingestion.

For each accepted pair, histories run in separate platform instances:
  [before], [after], [before, after], [after, before]
and MR1 is checked on the changed model's observed upstream URNs:
  forward:  S([before, after]) == S([after])
  reverse:  S([after, before]) == S([before])   (turns additions into withdrawals)
A sanity check compares each fresh state with the compiled depends_on set.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pilot import run, save  # noqa: E402


def dbt_urn(node_id, manifest, instance, platform='dbt'):
    from datahub.emitter.mce_builder import make_dataset_urn_with_platform_instance as mk
    nodes = {**manifest['nodes'], **manifest.get('sources', {})}
    n = nodes[node_id]
    name = n.get('alias') or n.get('identifier') or n['name']
    full = '.'.join(x for x in (n.get('database'), n.get('schema'), name) if x).lower()
    return mk(platform, full, instance, 'PROD')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifests', type=Path, required=True)
    p.add_argument('--server', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if urlparse(a.server).hostname not in ('localhost', '127.0.0.1'):
        p.error('loopback only')
    from datahub.ingestion.graph.client import DataHubGraph
    from datahub.ingestion.graph.config import DatahubClientConfig
    from datahub.metadata.schema_classes import UpstreamLineageClass
    graph = DataHubGraph(DatahubClientConfig(server=a.server))
    out = a.output.resolve()
    index = json.loads((a.manifests / 'index.json').read_text())
    results = []
    for case in index:
        if case['status'] != 'accepted':
            results.append({'id': case['id'], 'verdict': 'excluded', 'reason': case.get('reason')})
            continue
        files = {s: a.manifests / case['id'] / s / 'manifest.json' for s in ('before', 'after')}
        manifests = {s: json.loads(f.read_text()) for s, f in files.items()}
        node = case['node']['unique_id']
        states = {}
        # Observe after every step: [before, after] also yields [before], and
        # [after, before] also yields [after]. Four ingestions per pair instead of six.
        for hist in (('before', 'after'), ('after', 'before')):
            inst = 'rr' + hashlib.sha1((case['id'] + '/'.join(hist)).encode()).hexdigest()[:8]
            d = out / case['id'] / '-'.join(hist)
            ok = True
            for i, side in enumerate(hist):
                recipe = {'pipeline_name': f'rr-{inst}', 'source': {'type': 'dbt', 'config': {
                    'manifest_path': str(files[side]), 'target_platform': manifests[side]['metadata'].get('adapter_type') or 'postgres',
                    'platform_instance': inst, 'target_platform_instance': inst, 'include_column_lineage': False,
                    'infer_dbt_schemas': False, 'stateful_ingestion': {'enabled': False}}},
                    'sink': {'type': 'datahub-rest', 'config': {'server': a.server, 'mode': 'SYNC'}}}
                save(d / f'step{i}' / 'recipe.json', recipe)
                code = run(['datahub', 'ingest', '-c', str(d / f'step{i}' / 'recipe.json')], d / f'step{i}' / 'ingest.log', timeout=600)
                save(d / f'step{i}' / 'execution.json', {'exit_code': code})
                ok = ok and code == 0
                urn = dbt_urn(node, manifests[side], inst)
                samples = []
                for _ in range(3):
                    asp = graph.get_aspect(urn, UpstreamLineageClass)
                    samples.append(sorted(u.dataset.replace(f',{inst}.', ',') for u in (asp.upstreams if asp else [])))
                    time.sleep(1)
                save(d / f'step{i}' / 'observations.json', {'urn': urn, 'samples': samples, 'ingest_ok': ok})
                states[hist[:i + 1]] = frozenset(samples[-1]) if ok and samples[0] == samples[-1] else None
        expect = {s: frozenset(dbt_urn(x, manifests[s], 'X', manifests[s]['metadata'].get('adapter_type') or 'postgres').replace(',X.', ',') for x in
                               (case['before_deps'] if s == 'before' else case['after_deps'])) for s in ('before', 'after')}

        def check(x, y):
            if states.get(x) is None or states.get(y) is None:
                return 'not_testable'
            return 'holds' if states[x] == states[y] else 'violation'
        row = {'id': case['id'], 'repository': case['repository'], 'commit': case['commit'], 'path': case['path'],
               'removed': case['removed'], 'added': case['added'],
               'sanity_before': states.get(('before',)) == expect['before'],
               'sanity_after': states.get(('after',)) == expect['after'],
               'MR1_forward': check(('before', 'after'), ('after',)),
               'MR1_reverse': check(('after', 'before'), ('before',)),
               'states': {'/'.join(k): sorted(v) if v is not None else None for k, v in states.items()},
               'expected': {k: sorted(v) for k, v in expect.items()}}
        results.append(row)
        save(out / 'real-revision-results.json', results)
        print('MMREAL ' + json.dumps({k: row[k] for k in ('id', 'repository', 'commit', 'removed', 'added', 'sanity_before',
                                                         'sanity_after', 'MR1_forward', 'MR1_reverse', 'states', 'expected')}), flush=True)
    save(out / 'real-revision-results.json', results)
    print(json.dumps([{k: r.get(k) for k in ('id', 'MR1_forward', 'MR1_reverse', 'sanity_before', 'sanity_after', 'verdict')}
                      for r in results]))


if __name__ == '__main__':
    main()
