#!/usr/bin/env python3
"""Regenerate a normalized relation matrix from frozen raw instrumentation."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from score_export import path_label, score, check_headline, admissible

def generate():
    parts = sorted((ROOT / "evidence/frozen").glob("part-*.json"))
    if len(parts) != 12:
        raise ValueError("expected 12 evidence parts")
    jobs = [j for path in parts for j in json.loads(path.read_text())["jobs"]]
    check_headline(score({"schema": "frozen-instrumentation-export/v1", "jobs": jobs}))
    mapping = {}
    gates = {}
    for job in jobs:
        import re
        rep = int(re.search(r"rep(\d)", job["name"]).group(1))
        for row in job["rows"]:
            if row["type"] != "MMREL":
                continue
            r = row["data"]
            label = path_label(job["name"], r["path"])
            slot = mapping.setdefault(label, {}).setdefault(rep, {})
            if r["rel"] in slot:
                raise ValueError(f"duplicate relation {label}/{rep}/{r['rel']}")
            slot[r["rel"]] = r["verdict"]
    # Collect per-path integrity controls from the exact same evidence rows.
    from collections import defaultdict
    for job in jobs:
        import re
        rep = int(re.search(r"rep(\d)", job["name"]).group(1))
        grouped = defaultdict(lambda: {"rels": {}, "hist": [], "oracle": [], "cal": None})
        for row in job["rows"]:
            d, kind = row["data"], row["type"]
            path = d.get("path")
            if not path:
                continue
            r = grouped[path]
            if kind == "MMREL":
                r["rels"][d["rel"]] = d
            elif kind == "MMHIST":
                r["hist"].append(d)
            elif kind == "MMORACLE":
                r["oracle"].append(d)
            elif kind == "MMCAL":
                r["cal"] = d["false_alarms"]
        for path, record in grouped.items():
            if record["rels"]:
                gates.setdefault(path_label(job["name"], path), {})[rep] = admissible(record)
    if len(mapping) != 28:
        raise ValueError(f"expected 28 paths, found {len(mapping)}")
    paths = []
    for label, reps in sorted(mapping.items()):
        if set(reps) != {1,2,3}:
            raise ValueError(f"incomplete repetitions: {label}")
        ids = set(reps[1])
        if any(set(v) != ids for v in reps.values()):
            raise ValueError(f"relation coverage drift: {label}")
        relations = {}
        for rid in sorted(ids):
            values = [reps[i][rid] for i in (1,2,3)]
            relations[rid] = values[0] if len(set(values)) == 1 else "unstable"
        eligible = all(gates.get(label, {}).get(i, False) for i in (1,2,3))
        paths.append({"path":label, "admissible":eligible, "relations":relations if eligible else {}})
    return {"schema":"lineage-matrix/v1","paths":paths}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path)
    p.add_argument("--check", action="store_true")
    args = p.parse_args()
    result = generate()
    content = json.dumps(result, indent=2, sort_keys=True) + "\n"
    path = args.output or ROOT / "paper/tables/path-matrix.json"
    if args.check:
        if not path.exists() or json.loads(path.read_text()) != result:
            raise SystemExit("saved matrix does not match frozen instrumentation")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    print(f"Verified {len(result['paths'])} paths with three repetitions each")

if __name__ == "__main__":
    main()
