"""Compile both sides of each frozen real revision pair and save the manifests.

Reuses the compiler path of validate_public_revisions.py. Only pairs whose
continuing model identity and dependency delta are confirmed are exported.
"""
import argparse
import json
from pathlib import Path

from validate_public_revisions import identity, manifest_for


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cases', required=True, type=Path)
    p.add_argument('--repos', required=True, type=Path)
    p.add_argument('--profiles', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    cases = json.loads(a.cases.read_text())
    repos = json.loads(a.repos.read_text())
    index = []
    for k, case in enumerate(cases):
        rec = {'id': f'case{k:02d}', **case, 'status': 'rejected'}
        if case.get('change_kind') != 'modified':
            rec['reason'] = 'entity_creation_or_deletion'
            index.append(rec)
            continue
        repo = repos[case['repository']]
        sides = {}
        for label, rev in (('before', case['parent']), ('after', case['commit'])):
            j, meta = manifest_for(repo['path'], rev, repo.get('project_dir', '.'), a.profiles)
            if j is None:
                sides[label] = None
                rec[f'{label}_error'] = str(meta)[:500]
                continue
            node, diag = identity(j, case['path'])
            if node is None:
                sides[label] = None
                rec[f'{label}_error'] = str(diag)
                continue
            d = a.output / rec['id'] / label
            d.mkdir(parents=True, exist_ok=True)
            (d / 'manifest.json').write_text(json.dumps(j))
            sides[label] = node
        b, f = sides.get('before'), sides.get('after')
        if b and f and all(b[x] == f[x] for x in ('unique_id', 'database', 'schema', 'alias', 'materialized')) \
                and set(b['depends_on_nodes']) != set(f['depends_on_nodes']):
            rec.update(status='accepted', node=f, before_deps=b['depends_on_nodes'], after_deps=f['depends_on_nodes'],
                       removed=sorted(set(b['depends_on_nodes']) - set(f['depends_on_nodes'])),
                       added=sorted(set(f['depends_on_nodes']) - set(b['depends_on_nodes'])))
        else:
            rec['reason'] = 'identity_changed_or_no_delta_or_compile_failure'
        index.append(rec)
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
    print('EXPORTED', sum(r['status'] == 'accepted' for r in index), 'OF', len(index))


if __name__ == '__main__':
    main()
