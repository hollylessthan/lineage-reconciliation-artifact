#!/usr/bin/env python3
"""Audit original workflow ZIPs directly, without source-repository access.

Download the 60 artifacts from the frozen run into one directory before invoking:
  python scripts/audit_original_archives.py /path/to/archives --report audit.json
Never publish the ZIP archives or unfiltered logs without privacy screening.
"""
import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

FROZEN_SHA = "58c995f32abdf23d3441cc2bbb7053f7de247ee3"
def edges(items):
    if items is None:
        raise ValueError("missing state")
    return frozenset(tuple(x) if isinstance(x, list) else x for x in items)

def audit(directory):
    archives = sorted(Path(directory).glob("github-actions-artifact-*.zip"))
    issues, records, real_cases, digests = [], [], [], {}
    if len(archives) != 60:
        issues.append(f"Expected 60 archives, found {len(archives)}")
    for archive in archives:
        aid = archive.stem.split("-")[-1]
        if aid in digests:
            issues.append(f"duplicate archive id {aid}")
        digests[aid] = hashlib.sha256(archive.read_bytes()).hexdigest()
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if name.endswith("/metamorphic-results.json"):
                    d = json.loads(z.read(name))
                    records.append((aid, name, d))
                    if d.get("github_sha") != FROZEN_SHA:
                        issues.append(f"{aid}: frozen commit mismatch")
                    for rel in d.get("relations", []):
                        expected = rel.get("verdict")
                        if expected in ("not_applicable","not_testable"):
                            continue
                        a, b = rel.get("state_a"), rel.get("state_b")
                        if a is None or b is None:
                            issues.append(f"{aid}/{name}: missing relation state")
                            continue
                        cmp = rel.get("comparison")
                        if not isinstance(cmp, dict) or "holds" not in cmp:
                            issues.append(f"{aid}/{name}: missing comparator")
                            continue
                        # Equality relations can be checked without any asserted verdict.
                        if not (rel.get("comparison") and rel.get("comparison").get("holds") is not None):
                            continue
                        calculated = rel.get("comparison",{}).get("holds")
                        if rel.get("relation") in ("MR1a","MR1b","MR1c","MR2a","MR2b","MR3","MR5","MR5i","MR7","MR9a","MR9b","MR9c"):
                            calculated = edges(a) == edges(b)
                        if calculated != cmp["holds"]:
                            issues.append(f"{aid}/{name}/{rel['relation']}: comparison disagrees with edges")
                if name.endswith("/real-revision-results.json"):
                    cases = json.loads(z.read(name))
                    if len(cases) != 9:
                        issues.append(f"{aid}: expected 9 real revision cases")
                    for c in cases:
                        real_cases.append((aid,c))
                        s = c["states"]
                        forward = "holds" if edges(s["before/after"]) == edges(s["after"]) else "violation"
                        reverse = "holds" if edges(s["after/before"]) == edges(s["before"]) else "violation"
                        if (forward, reverse) != (c["MR1_forward"], c["MR1_reverse"]):
                            issues.append(f"{aid}/{c['id']}: real-revision comparison mismatch")
                        if edges(s["before"]) != edges(c["expected"]["before"]) or edges(s["after"]) != edges(c["expected"]["after"]):
                            issues.append(f"{aid}/{c['id']}: real-revision expected state mismatch")
                        if c.get("sanity_before") is not True or c.get("sanity_after") is not True:
                            issues.append(f"{aid}/{c['id']}: failed sanity check")
    if len(records) != 84:
        issues.append(f"Expected 84 structured results, found {len(records)}")
    if len(real_cases) != 27:
        issues.append(f"Expected 27 real-revision observations, found {len(real_cases)}")
    ids = Counter(c["id"] for _, c in real_cases)
    if len(ids) != 9 or any(n != 3 for n in ids.values()):
        issues.append("real-revision IDs are not nine cases with three repetitions")
    return {"schema":"archive-reconciliation/v1","archives":len(archives),
            "structured_results":len(records),"real_revision_records":len(real_cases),
            "real_revision_case_repetitions":dict(sorted(ids.items())),
            "frozen_commit_matches":sum(d.get("github_sha")==FROZEN_SHA for _,_,d in records),
            "archive_sha256":dict(sorted(digests.items())),
            "issues":issues,
            "scope":"Original ZIP structural evidence, recorded edge comparisons and real-revision expected-state checks. Does not independently compare log-export parts byte-for-byte, rerun containers, or verify external contract semantics."}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("archives",type=Path)
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    result=audit(a.archives)
    output=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(output)
    else:
        print(output)
    if result["issues"]:
        raise SystemExit("Archive audit FAILED")
if __name__=="__main__":
    main()
