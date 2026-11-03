"""Summarize captured OpenLineage events per task run: which event types carry inputs/outputs."""
import json
import sys
from collections import defaultdict

runs = defaultdict(list)
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    e = json.loads(line)
    job = e.get('job', {}).get('name', '?')
    runs[(job, e['run']['runId'])].append(e)
rows = []
for (job, run), evs in sorted(runs.items(), key=lambda x: x[1][0]['eventTime']):
    seq = []
    for e in sorted(evs, key=lambda x: x['eventTime']):
        ins = None if 'inputs' not in e else sorted(i['name'] for i in e['inputs'])
        outs = None if 'outputs' not in e else sorted(o['name'] for o in e['outputs'])
        seq.append({'type': e['eventType'], 'inputs': ins, 'outputs': outs,
                    'producer': e.get('producer', '')[-60:]})
    rows.append({'job': job, 'events': seq})
for r in rows:
    print('PROBE ' + json.dumps(r))
