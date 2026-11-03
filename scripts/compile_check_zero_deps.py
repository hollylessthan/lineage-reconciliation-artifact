"""Compile-check the strict zero-dependency events found by mine_dbt_history.py.

For each distinct (commit, path) strict event, parse both sides with dbt (no warehouse
connection; `dbt parse` only) and record whether the compiled manifest confirms the
transition: the model keeps its identity and its `depends_on.nodes` goes from nonempty
to empty. Repositories that share an identical event list (copied histories) are
reported once. Adapter type is not recorded in the projects, so each side is parsed
with the first adapter in ADAPTERS that succeeds; an environment binding only.

Outputs a JSON report and, with --export, the accepted manifests in the layout read by
real_revisions.py (index.json plus caseNN/{before,after}/manifest.json).
Probe after protocol-v1; not part of the frozen measurement.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

from validate_public_revisions import identity, manifest_for

ADAPTERS = ('duckdb', 'snowflake', 'bigquery', 'databricks', 'postgres')
PROFILE_OUTPUTS = {
    'duckdb': {'type': 'duckdb', 'path': '/tmp/zero-dep-check.duckdb'},
    'snowflake': {'type': 'snowflake', 'account': 'offline', 'user': 'offline', 'password': 'offline',
                  'database': 'offline', 'warehouse': 'offline', 'schema': 'offline', 'threads': 1},
    'bigquery': {'type': 'bigquery', 'method': 'oauth', 'project': 'offline-dbt-validation',
                 'dataset': 'offline', 'threads': 1},
    'databricks': {'type': 'databricks', 'host': 'offline.invalid', 'http_path': '/sql/offline',
                   'token': 'offline', 'schema': 'offline', 'threads': 1},
    'postgres': {'type': 'postgres', 'host': 'localhost', 'user': 'offline', 'password': 'offline',
                 'port': 5432, 'dbname': 'offline', 'schema': 'offline', 'threads': 1},
}


def profiles(dirpath, name, adapter):
    dirpath.mkdir(parents=True, exist_ok=True)
    out = PROFILE_OUTPUTS[adapter]
    lines = []
    for prof in sorted({name, 'default'}):
        lines += [f'{prof}:', '  target: dev', '  outputs:', '    dev:']
        lines += [f'      {k}: {json.dumps(v)}' for k, v in out.items()]
    (dirpath / 'profiles.yml').write_text('\n'.join(lines) + '\n')


def project_dir(repo, rev, path):
    files = subprocess.run(['git', '-C', str(repo), 'ls-tree', '-r', '--name-only', rev],
                           capture_output=True, text=True).stdout.split()
    cands = [str(Path(f).parent) for f in files if Path(f).name == 'dbt_project.yml'
             and (str(Path(f).parent) == '.' or path.startswith(str(Path(f).parent) + '/'))]
    return max(cands, key=len) if cands else None


def profile_name(repo, rev, pdir):
    text = subprocess.run(['git', '-C', str(repo), 'show', f'{rev}:{Path(pdir, "dbt_project.yml").as_posix()}'],
                          capture_output=True, text=True).stdout
    m = re.search(r"^profile:\s*['\"]?([\w-]+)", text, re.M)
    return m.group(1) if m else 'default'


def parse_side(repo, rev, pdir, path, work):
    name = profile_name(repo, rev, pdir)
    errors = {}
    for adapter in ADAPTERS:
        prof = work / f'profiles-{adapter}'
        profiles(prof, name, adapter)
        j, meta = manifest_for(repo, rev, pdir, prof)
        if j is None:
            errors[adapter] = meta.get('error')
            continue
        node, diag = identity(j, str(Path(path).relative_to(pdir)) if pdir != '.' else path)
        return j, node, adapter, diag
    return None, None, None, errors


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mining', type=Path, required=True)
    p.add_argument('--clones', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--export', type=Path)
    p.add_argument('--per-repo', type=int, default=2, help='export at most this many confirmed events per repository')
    p.add_argument('--max-export', type=int, default=10)
    a = p.parse_args()
    data = json.loads(a.mining.read_text())
    seen, report, index = {}, [], []
    for r in data['repos']:
        if not r.get('active'):
            continue
        events = [e for e in r.get('to_zero_events', []) if e['kind'] == 'to_zero_strict']
        if not events:
            continue
        sig = tuple(sorted((e['commit'], e['path']) for e in events))
        if sig in seen:
            report.append({'repo': r['repo'], 'duplicate_of': seen[sig], 'events': len(events)})
            continue
        seen[sig] = r['repo']
        repo = a.clones / r['repo'].replace('/', '__')
        if not repo.exists():
            subprocess.run(['git', 'clone', '-q', '--filter=blob:none', '--no-checkout',
                            f"https://github.com/{r['repo']}", str(repo)], check=False)
        for e in events:
            rec = {'repo': r['repo'], 'commit': e['commit'], 'parent': e['parent'], 'path': e['path'],
                   'static_removed': e['removed']}
            pdir = project_dir(repo, e['commit'], e['path'])
            if pdir is None:
                rec['result'] = 'no_dbt_project'
                report.append(rec)
                continue
            sides = {}
            for label, rev in (('before', e['parent']), ('after', e['commit'])):
                j, node, adapter, diag = parse_side(repo, rev, pdir, e['path'], a.output.parent / 'work')
                sides[label] = (j, node)
                rec[f'{label}_adapter'] = adapter
                rec[f'{label}_deps'] = node['depends_on_nodes'] if node else None
                if node is None:
                    rec[f'{label}_error'] = diag
            b, f = sides['before'][1], sides['after'][1]
            if b is None or f is None:
                rec['result'] = 'parse_failed'
            elif any(b[x] != f[x] for x in ('unique_id', 'database', 'schema', 'alias')):
                rec['result'] = 'identity_changed'
            elif b['depends_on_nodes'] and not f['depends_on_nodes']:
                rec['result'] = 'confirmed_to_zero'
            else:
                rec['result'] = 'not_confirmed'
            report.append(rec)
            exported_here = sum(x['repository'] == r['repo'] for x in index)
            if a.export and rec['result'] == 'confirmed_to_zero' and exported_here < a.per_repo and len(index) < a.max_export:
                rec['exported'] = f'zero{len(index):02d}'
                cid = f'zero{len(index):02d}'
                for label in ('before', 'after'):
                    d = a.export / cid / label
                    d.mkdir(parents=True, exist_ok=True)
                    (d / 'manifest.json').write_text(json.dumps(sides[label][0]))
                index.append({'id': cid, 'repository': r['repo'], 'commit': e['commit'], 'parent': e['parent'],
                              'path': e['path'], 'status': 'accepted', 'node': f, 'before_deps': b['depends_on_nodes'],
                              'after_deps': [], 'removed': b['depends_on_nodes'], 'added': []})
            print(json.dumps({k: rec.get(k) for k in ('repo', 'commit', 'path', 'result', 'before_adapter')}), flush=True)
    counts = {}
    for rec in report:
        key = 'duplicate_history' if 'duplicate_of' in rec else rec['result']
        counts[key] = counts.get(key, 0) + 1
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({'summary': counts, 'events': report}, indent=2) + '\n')
    if a.export:
        (a.export / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
