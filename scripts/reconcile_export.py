#!/usr/bin/env python3
"""Exact multiset reconciliation of source structured ZIPs against sanitized export.
Usage: python scripts/reconcile_export.py /directory/of/60/original-zips
This intentionally compares the complete preserved MMREL and MMHIST fields,
independent of fragile log job names, while checking cardinalities and duplicates.
"""
import argparse
import json
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def canonical(row):
    return json.dumps(row, sort_keys=True, separators=(",",":"), ensure_ascii=False)
def original(directory):
    rel, hist = Counter(), Counter()
    zips = sorted(directory.glob("github-actions-artifact-*.zip"))
    if len(zips) != 60:
        raise ValueError(f"expected 60 original ZIP archives; got {len(zips)}")
    for path in zips:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if not name.endswith("/metamorphic-results.json"):
                    continue
                d = json.loads(z.read(name))
                p = d["path"]
                for r in d["relations"]:
                    rel[canonical([p,r["relation"],r["verdict"],r.get("state_a"),r.get("state_b")])] += 1
                for x in d["histories"]:
                    hist[canonical([p,x.get("history"),x.get("edges"),x.get("stable")])] += 1
    return rel, hist
def curated():
    rel, hist = Counter(), Counter()
    parts = sorted((ROOT/"evidence/frozen").glob("part-*.json"))
    if len(parts) != 12:
        raise ValueError(f"expected 12 sanitized parts, found {len(parts)}")
    for part in parts:
        for j in json.loads(part.read_text())["jobs"]:
            for r in j["rows"]:
                x = r["data"]
                if r["type"] == "MMREL":
                    rel[canonical([x["path"],x["rel"],x["verdict"],x.get("a"),x.get("b")])] += 1
                if r["type"] == "MMHIST":
                    hist[canonical([x["path"],x.get("history"),x.get("edges"),x.get("stable")])] += 1
    return rel,hist
def check(directory):
    raw=original(directory)
    pub=curated()
    problems=[]
    for kind,a,b,expected in zip(("relations","histories"),raw,pub,(738,1158)):
        if sum(a.values())!=expected or sum(b.values())!=expected:
            problems.append(f"{kind}: unexpected count {sum(a.values())} versus {sum(b.values())}")
        if a != b:
            problems.append(f"{kind}: mismatched multiset, missing={sum((a-b).values())}, extra={sum((b-a).values())}")
    return {"raw_relation_rows":sum(raw[0].values()),"export_relation_rows":sum(pub[0].values()),
            "raw_history_rows":sum(raw[1].values()),"export_history_rows":sum(pub[1].values()),
            "exact_multisets_match":not problems,"problems":problems,
            "excluded_fields":"raw namespace IDs, server logs and private orchestration metadata were deliberately not exported"}
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("raw_archives",type=Path)
    a=p.parse_args()
    result=check(a.raw_archives)
    print(json.dumps(result,indent=2))
    if result["problems"]:
        raise SystemExit(1)
