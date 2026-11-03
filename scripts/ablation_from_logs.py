"""Contract-conditioning ablation recomputed from frozen protocol-v1 job logs.

For every path whose contract is not Replace, the conditioned harness marks MR1a/b/c
`not_applicable`. This script asks what an unconditioned harness would have reported:
it looks up the two histories of each MR1 relation among the path's logged MMHIST
observations and compares their edge sets for equality (the Replace comparator).
A relation whose histories were not both observed is reported as `unobserved`, so the
count is a lower bound. Admissibility uses the same rules as analyze_protocol.py.

Usage: python scripts/ablation_from_logs.py RUN_ID
Analysis only; not part of the frozen measurement.
"""
import argparse
import json
from collections import defaultdict

import analyze_protocol as ap

MR1 = {'MR1a': (('r0', 'r1'), ('r1',)), 'MR1b': (('r0', 'empty'), ('empty',)), 'MR1c': (('r1', 'r0'), ('r0',))}


def revision(step):
    # 'rev:r1' (batch) or 'ol:r1:full' (OpenLineage); only full-run OL histories count for MR1.
    parts = step.split(':')
    if len(parts) < 2 or (parts[0] == 'ol' and parts[-1] != 'full'):
        return None
    return parts[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('run_id')
    run_id = p.parse_args().run_id
    out = defaultdict(dict)
    for j in ap.jobs(run_id):
        m = ap.REP.search(j['name'])
        if not m or j['conclusion'] == 'skipped':
            continue
        rep = int(m.group(1))
        log = ap.gh(f"repos/{ap.REPO}/actions/jobs/{j['id']}/logs")
        hist, mr1a = {}, {}
        for line in log.splitlines():
            for tag in ('MMHIST ', 'MMREL '):
                i = line.find(tag)
                if i < 0:
                    continue
                r = json.loads(line[i + len(tag):])
                if tag == 'MMHIST ' and 'edges' in r:
                    key = tuple(revision(s) for s in r['history'])
                    if None not in key:
                        hist.setdefault((r['path'], key), sorted(map(tuple, r['edges'])))
                elif tag == 'MMREL ' and r['rel'] == 'MR1a':
                    mr1a[r['path']] = r['verdict']
        for path, rec in ap.parse(log).items():
            if path == 'dh-real' or mr1a.get(path) != 'not_applicable':
                continue
            ok, _ = ap.admissible(rec)
            for rid, (a, b) in MR1.items():
                ha, hb = hist.get((path, a)), hist.get((path, b))
                v = 'unobserved' if ha is None or hb is None else ('alarm' if ha != hb else 'agree')
                out[(ap.label(j['name'], path), rid)][rep] = (ok, v)
    total, paths = 0, set()
    print('| Path | Relation | Unconditioned outcome (rep1/rep2/rep3) |\n|---|---|---|')
    for (label, rid), reps in sorted(out.items()):
        vals = [reps.get(r, (False, 'missing')) for r in (1, 2, 3)]
        print(f"| {label} | {rid} | {'/'.join(v for _, v in vals)} |")
        if all(ok and v == 'alarm' for ok, v in vals):
            total += 1
            paths.add(label)
    print(f'\nReplicated (3/3 admissible) false alarms avoided: {total} on {len(paths)} paths')


if __name__ == '__main__':
    main()
