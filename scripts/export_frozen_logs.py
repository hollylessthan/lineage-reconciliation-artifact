#!/usr/bin/env python3
"""Private-to-public frozen-run export. Requires authorized gh CLI access to source repo.

No source repo URL, access token, or unfiltered log line is emitted.
Run from a trusted environment; review the export before publishing.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

TAGS = ("MMREL", "MMHIST", "MMCAL", "MMORACLE", "MMREAL")

def gh(path):
    return subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout

def jobs(repo, run):
    all_jobs = []
    page = 1
    while True:
        obj = json.loads(gh(f"repos/{repo}/actions/runs/{run}/jobs?per_page=100&page={page}"))
        items = obj["jobs"]
        all_jobs.extend(items)
        if len(items) < 100:
            break
        page += 1
    return sorted(all_jobs, key=lambda x:x["id"])

def extract(log):
    rows = []
    for line in log.splitlines():
        match = re.search(r"\b(MMREL|MMHIST|MMCAL|MMORACLE|MMREAL) (\{.*\})\s*$", line)
        if not match:
            continue
        data = json.loads(match.group(2))
        kind = match.group(1)
        if kind == "MMREL":
            clean = {k:data.get(k) for k in ("path","rel","verdict","a","b")}
        elif kind == "MMHIST":
            clean = {k:data.get(k) for k in ("path","history","edges","stable")}
        elif kind == "MMCAL":
            clean = {k:data.get(k) for k in ("path","false_alarms")}
        elif kind == "MMORACLE":
            clean = {k:data.get(k) for k in ("path","history","match")}
        else:
            clean = {k:data.get(k) for k in ("id","MR1_forward","MR1_reverse","sanity_before","sanity_after")}
        rows.append({"type":kind,"data":clean})
    return rows

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True, help="Authorized private source repo in owner/name form")
    p.add_argument("--run-id", required=True, type=int)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--expected-jobs", type=int, default=60)
    args = p.parse_args()
    records = []
    for job in jobs(args.source, args.run_id):
        if job["conclusion"] == "skipped":
            continue
        rows = extract(gh(f"repos/{args.source}/actions/jobs/{job['id']}/logs"))
        records.append({"name":job["name"], "rows":rows})
    if len(records) != args.expected_jobs:
        raise SystemExit(f"INCOMPLETE: expected {args.expected_jobs} jobs; got {len(records)}")
    path_records = sum(len({row["data"]["path"] for row in entry["rows"] if row["type"] == "MMREL"}) for entry in records)
    if path_records != 84:
        raise SystemExit(f"INCOMPLETE: expected 84 path-repetitions, got {path_records}")
    if not all(entry["rows"] for entry in records if "export-revisions" not in entry["name"]):
        raise SystemExit("INCOMPLETE: a non-export job has no instrumentation records")
    # Store only whitelisted records, with no account-specific job IDs or log URLs.
    obj = {"schema":"frozen-instrumentation-export/v1","jobs":records}
    text = json.dumps(obj,sort_keys=True,separators=(",",":"))+"\n"
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(text)
    print("Exported",len(records),"jobs to",args.output)

if __name__=="__main__":
    main()
