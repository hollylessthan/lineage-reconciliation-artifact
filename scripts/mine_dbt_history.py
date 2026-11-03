"""Item 4 probe: how often do real dbt models lose all their dependencies?

Collects public repositories containing dbt_project.yml (GitHub code search), clones
them, and walks the history of model .sql files. For each modification of an existing
model it extracts static ref()/source() dependencies before and after, and classifies:

  withdrawal       at least one dependency removed, some remain
  to_zero_strict   all dependencies removed; the new file has no Jinja calls other than config()
  to_zero_jinja    all ref()/source() removed but other Jinja remains (could still reference relations)
  model_deleted    model file deleted (entity omission, a different case from an empty declaration)

Static extraction is an approximation (macros, dynamic refs); the to_zero_strict class is the
conservative count. This is a probe, not part of protocol-v1.
"""
import argparse
import concurrent.futures as cf
import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

REF = re.compile(r"""\{\{[^}]*?\bref\(\s*['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]+)['"])?""")
SRC = re.compile(r"""\{\{[^}]*?\bsource\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]""")
JINJA = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}", re.S)
CONFIG_ONLY = re.compile(r"^\s*config\s*\(", re.S)


def sh(args, cwd=None, timeout=300):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def deps(text):
    out = {('ref',) + tuple(x for x in m.groups() if x) for m in REF.finditer(text)}
    out |= {('source', a, b) for a, b in SRC.findall(text)}
    return out


def only_config_jinja(text):
    for m in JINJA.finditer(text):
        body = (m.group(1) or m.group(2) or '').strip()
        if body and not CONFIG_ONLY.match(body) and not body.startswith(('-', '#')):
            return False
    return True


def materialization(text):
    m = re.search(r"materialized\s*=\s*['\"](\w+)['\"]", text)
    return m.group(1) if m else 'default'


def candidates(limit, min_stars):
    """Repositories with a dbt_project.yml from GitHub code search, excluding forks.
    (Per-repository metadata calls are unavailable here; activity is filtered after cloning.)"""
    seen, repos = set(), []
    for page in range(1, 11):
        r = sh(['gh', 'api', '-X', 'GET', 'search/code', '-f', 'q=filename:dbt_project.yml',
                '-f', 'per_page=100', '-f', f'page={page}', '--jq',
                '.items[].repository | [.full_name, .fork] | @tsv'])
        rows = [l.split('\t') for l in r.stdout.splitlines() if l.strip()]
        if not rows:
            break
        for name, fork in rows:
            if fork == 'false' and name not in seen:
                seen.add(name)
                repos.append({'repo': name})
        time.sleep(7)  # code search rate limit
    return repos[:limit]


def scan(repo, workdir):
    d = workdir / repo.replace('/', '__')
    if not d.exists():
        r = sh(['git', 'clone', '-q', '--filter=blob:none', '--no-checkout', f'https://github.com/{repo}', str(d)], timeout=600)
        if r.returncode:
            return {'repo': repo, 'error': 'clone failed'}
    log = sh(['git', 'log', '--no-renames', '--format=@@%H %P', '--name-status', '--', '*.sql'], cwd=d, timeout=600)
    events, counts = [], Counter()
    commit = parent = None
    for line in log.stdout.splitlines():
        if line.startswith('@@'):
            parts = line[2:].split()
            commit, parent = parts[0], (parts[1] if len(parts) > 1 else None)
            continue
        if not line.strip() or parent is None:
            continue
        status, *paths = line.split('\t')
        path = paths[-1]
        if '/models/' not in '/' + path:
            continue
        if status == 'D':
            counts['model_deleted'] += 1
            continue
        if status != 'M':
            continue
        before = sh(['git', 'show', f'{parent}:{path}'], cwd=d).stdout
        after = sh(['git', 'show', f'{commit}:{path}'], cwd=d).stdout
        b, a = deps(before), deps(after)
        counts['modified'] += 1
        if b == a:
            continue
        counts['dep_change'] += 1
        if b and not a:
            kind = 'to_zero_strict' if only_config_jinja(after) else 'to_zero_jinja'
        elif b - a:
            kind = 'withdrawal'
        else:
            continue
        counts[kind] += 1
        if kind.startswith('to_zero'):
            events.append({'commit': commit, 'parent': parent, 'path': path, 'kind': kind,
                           'removed': sorted('.'.join(x) for x in b), 'materialized': materialization(after)})
    return {'repo': repo, 'counts': dict(counts), 'to_zero_events': events, 'active': counts['modified'] >= 10}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--limit', type=int, default=120)
    p.add_argument('--min-stars', type=int, default=3)
    p.add_argument('--workdir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.workdir.mkdir(parents=True, exist_ok=True)
    repos = candidates(a.limit, a.min_stars)
    (a.output.parent).mkdir(parents=True, exist_ok=True)
    results = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(lambda r: {**r, **scan(r['repo'], a.workdir)}, repos):
            results.append(res)
            print(res['repo'], res.get('counts', res.get('error')), flush=True)
    scanned = [r for r in results if 'counts' in r]
    ok = [r for r in scanned if r['active']]  # at least 10 modifications of existing models
    total = Counter()
    for r in ok:
        total.update(r['counts'])
    summary = {
        'repos_cloned': len(scanned), 'repos_active': len(ok), 'repos_failed': len(results) - len(scanned),
        'repos_with_dep_changes': sum(r['counts'].get('dep_change', 0) > 0 for r in ok),
        'repos_with_withdrawal': sum(r['counts'].get('withdrawal', 0) + r['counts'].get('to_zero_strict', 0)
                                     + r['counts'].get('to_zero_jinja', 0) > 0 for r in ok),
        'repos_with_to_zero_strict': sum(r['counts'].get('to_zero_strict', 0) > 0 for r in ok),
        'repos_with_to_zero_any': sum((r['counts'].get('to_zero_strict', 0) + r['counts'].get('to_zero_jinja', 0)) > 0 for r in ok),
        'totals': dict(total),
    }
    a.output.write_text(json.dumps({'summary': summary, 'repos': results}, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
