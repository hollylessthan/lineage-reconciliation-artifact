#!/usr/bin/env python3
"""Offline scoring of a curated frozen-instrumentation export.

Input is produced by export_frozen_logs.py. No network or source repository needed.
The scorer uses recorded edge observations and integrity controls; it does not
claim to rerun the original catalogs.
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from metamorphic_core import compare, batch_relations, openlineage_relations, fault_relations, verdict as core_verdict, State

REPLACE = "R"
ADDITIVE = {"dh-ol-patch", "dh-view-incremental", "om-dbt-default"}
UNDETERMINED = {"om-ol"}
MR1 = {
    "MR1a": (("r0", "r1"), ("r1",)),
    "MR1b": (("r0", "empty"), ("empty",)),
    "MR1c": (("r1", "r0"), ("r0",)),
}
EXEMPT = ("inputs_in_start", "inputs_omitted_complete", "inputs_in_complete", "start_only")


def path_label(job_name, path):
    m = re.search(r"\(([^)]*)\)", job_name)
    extra = m.group(1) if m else ""
    if "olpatch" in job_name:
        return path + " [" + extra.split(",")[0] + "]"
    suffix = job_name.split(" / ")[-1]
    if suffix.startswith("datahub-old"):
        return path + " [DataHub 1.5.0]"
    if "openmetadata-old" in suffix:
        return path + " [OpenMetadata 1.13.6]"
    return path


def normalized_history(steps):
    result = []
    for step in steps:
        parts = step.split(":")
        if len(parts) < 2 or (parts[0] == "ol" and parts[-1] != "full"):
            return None
        result.append(parts[1])
    return tuple(result)


def admissible(record):
    if record["cal"] != 0 or not record["hist"] or not record["rels"]:
        return False
    if any(h.get("stable") is not True or h.get("error") for h in record["hist"]):
        return False
    if any(d["verdict"] in ("not_testable", "control_failed") for d in record["rels"].values()):
        return False
    for d in record["oracle"]:
        history = d.get("history") or []
        if not any(any(step.endswith(":" + x) for x in EXEMPT) for step in history):
            if d.get("match") is False:
                return False
    return True



def recompute_verdict(record, relation_id, history, path):
    """Independently derive the verdict from edge states, never from a saved label."""
    stored = record["verdict"]
    if stored in ("not_applicable", "not_testable"):
        if record.get("a") is not None or record.get("b") is not None:
            raise ValueError("unscored relation has recorded states: " + relation_id)
        return stored
    family = openlineage_relations() if path.endswith("-ol") or "ol-patch" in path else batch_relations(supports_omit=True) + fault_relations()
    matches = [rel for rel in family if rel.id == relation_id]
    if len(matches) != 1:
        raise ValueError("unknown relation: " + path + "/" + relation_id)
    relation = matches[0]
    if record.get("a") is None or record.get("b") is None:
        raise ValueError("scored relation has missing states")
    a = frozenset(tuple(edge) for edge in record["a"])
    b = frozenset(tuple(edge) for edge in record["b"])
    bounds = []
    if relation.comparator == "additive_bound":
        for steps in relation.bound_from:
            wanted = [":".join(step) for step in steps]
            candidates = [h["edges"] for h in history if h.get("history") == wanted and h.get("edges") is not None]
            if not candidates:
                raise ValueError("missing single-step bound: " + path + "/" + relation_id + "/" + str(wanted))
            if any(v != candidates[0] for v in candidates):
                raise ValueError("inconsistent bound observation")
            bounds.append(frozenset(tuple(edge) for edge in candidates[0]))
    contract = "additive" if path in ADDITIVE else "undetermined" if path in UNDETERMINED else "replace"
    calculated = core_verdict(relation, contract, compare(relation, a, b, bounds))
    if calculated != stored:
        raise ValueError("recorded verdict disagrees with edge evidence: " + path + "/" + relation_id + ": " + stored + " != " + calculated)
    return calculated

def score(payload, expected_jobs=60):
    if payload.get("schema") != "frozen-instrumentation-export/v1":
        raise ValueError("wrong export schema")
    jobs = payload.get("jobs", [])
    if len(jobs) != expected_jobs:
        raise ValueError(f"incomplete jobs: {len(jobs)}, expected {expected_jobs}")
    paths = defaultdict(dict)
    for job in jobs:
        name = job["name"]
        m = re.search(r"rep(\d)", name)
        if not m:
            raise ValueError("unlabeled repetition")
        rep = int(m.group(1))
        per_path = defaultdict(lambda: {"rels": {}, "hist": [], "oracle": [], "cal": None})
        for row in job.get("rows", []):
            d, kind = row["data"], row["type"]
            path = d.get("path")
            if not path:
                continue
            r = per_path[path]
            if kind == "MMREL":
                rid = d["rel"]
                if rid in r["rels"]:
                    raise ValueError("duplicate relation")
                r["rels"][rid] = d
            elif kind == "MMHIST":
                r["hist"].append(d)
            elif kind == "MMORACLE":
                r["oracle"].append(d)
            elif kind == "MMCAL":
                if r["cal"] is not None:
                    raise ValueError("duplicate calibration")
                r["cal"] = d["false_alarms"]
        for path, r in per_path.items():
            if not r["rels"]:
                continue
            key = path_label(name, path)
            if rep in paths[key]:
                raise ValueError("duplicate path repetition")
            paths[key][rep] = r
    if len(paths) != 28 or sum(map(len, paths.values())) != 84:
        raise ValueError(f"expected 28 paths x 3, got {len(paths)} paths and {sum(map(len, paths.values()))} repetitions")

    violations = []
    excluded = []
    false_alarms = []
    deviations = []
    for name, reps in sorted(paths.items()):
        if set(reps) != {1, 2, 3}:
            raise ValueError("missing repetition for " + name)
        passed = [admissible(reps[i]) for i in (1, 2, 3)]
        if not all(passed):
            if any(passed):
                raise ValueError("partial admission requires explicit disposition: " + name)
            excluded.append(name)
            continue
        ids = set(reps[1]["rels"])
        if any(set(reps[i]["rels"]) != ids for i in (2, 3)):
            raise ValueError("relation coverage drift")
        for rid in sorted(ids):
            records = [reps[i]["rels"][rid] for i in (1, 2, 3)]
            verdicts = {recompute_verdict(d, rid, reps[i]["hist"], name.split(" [")[0]) for i, d in zip((1, 2, 3), records)}
            if len(verdicts) != 1:
                raise ValueError("nonreplicated relation: " + name + "/" + rid)
            verdict = verdicts.pop()
            if verdict == "violation":
                if name.split(" [")[0] == "om-ol" and rid in ("MR9a", "MR9c"):
                    deviations.append([name, rid])
                else:
                    violations.append([name, rid])
        base = name.split(" [")[0]
        if base in ADDITIVE or base in UNDETERMINED:
            for rid, (a, b) in MR1.items():
                comparisons = []
                for i in (1, 2, 3):
                    observations = {}
                    for h in reps[i]["hist"]:
                        key = normalized_history(h.get("history", []))
                        if key is not None and "edges" in h:
                            observations.setdefault(key, sorted(h["edges"]))
                    comparisons.append(observations[a] != observations[b] if a in observations and b in observations else None)
                if comparisons == [True] * 3:
                    false_alarms.append([name, rid])
    result = {
        "paths": len(paths), "admissible": len(paths) - len(excluded),
        "excluded": excluded, "violations": violations,
        "documented_deviations": deviations, "false_alarms": false_alarms
    }
    return result


def check_headline(result):
    if (result["paths"], result["admissible"], len(result["excluded"]),
        sum(r == "MR1b" for _, r in result["violations"]),
        sum(r.startswith("MR9") for _, r in result["violations"]),
        len(result["documented_deviations"]), len(result["false_alarms"])) != (28, 26, 2, 17, 2, 4, 8):
        raise AssertionError("record-derived findings differ from published results")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = score(json.loads(args.input.read_text()))
    check_headline(result)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
