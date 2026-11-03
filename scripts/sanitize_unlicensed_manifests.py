#!/usr/bin/env python3
"""Strip all source-derived content from selected third-party dbt manifests.

Preserve only declarative lineage metadata needed for catalog replay.
Run on a private checkout before a new public release. This updates the
working-copy checksum inventory and fails unless dependencies are preserved.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evidence/compiler/zero-manifests"
INDEX = BASE / "index.json"
HASHES = ROOT / "evidence/import/SHA256.json"
UNLICENSED = {"zero01", "zero03", "zero04", "zero05"}
META = ("adapter_type", "dbt_schema_version", "dbt_version", "project_name", "quoting")
NODE = ("unique_id", "name", "alias", "identifier", "database", "schema",
        "relation_name", "resource_type", "package_name", "fqn", "enabled", "depends_on")
SOURCE = NODE  # minimal release profile omits optional third-party source descriptors
REQUIRED_TOP = ("nodes", "sources", "metadata")

def item(value, keys):
    return {k: value[k] for k in keys if k in value}

def minimize(doc):
    out = {k: {} for k in
           ("nodes", "sources", "macros", "docs", "exposures", "metrics",
            "semantic_models", "saved_queries", "unit_tests", "selectors",
            "groups", "group_map", "disabled")}
    out["metadata"] = item(doc["metadata"], META)
    for category, keys in (("nodes", NODE), ("sources", SOURCE)):
        out[category] = {key: item(value, keys) for key, value in doc.get(category, {}).items()}
    for key in ("parent_map", "child_map"):
        if key in doc:
            out[key] = doc[key]
    # dbt ingestion uses configuration to distinguish models; only public
    # declarative materialization and enablement settings are retained.
    for key, original in doc.get("nodes", {}).items():
        entry = out["nodes"][key]
        if "config" in original:
            entry["config"] = item(original["config"], ("materialized", "enabled"))
    return out

def graph(doc):
    return {key: tuple(value.get("depends_on", {}).get("nodes", []))
            for key, value in doc.get("nodes", {}).items()}

def run(check=False):
    index = json.loads(INDEX.read_text())
    indexed = {r["id"]: r for r in index}
    assert UNLICENSED <= set(indexed)
    registry = json.loads(HASHES.read_text())
    original_count = len(registry["sha256"])
    changed = 0
    for case_id in sorted(UNLICENSED):
        case = indexed[case_id]
        for side in ("before", "after"):
            path = BASE / case_id / side / "manifest.json"
            doc = json.loads(path.read_text())
            clean = minimize(doc)
            if graph(clean) != graph(doc):
                raise ValueError(f"Lineage graph changed: {path}")
            target = case["node"]["unique_id"]
            expected = case[f"{side}_deps"]
            if target not in clean["nodes"]:
                raise ValueError(f"Missing target: {target}")
            actual = clean["nodes"][target].get("depends_on", {}).get("nodes", [])
            if sorted(actual) != sorted(expected):
                raise ValueError(f"Dependency mismatch for {case_id}/{side}: {actual}")
            raw = json.dumps(clean, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            if any(key in raw for key in ('"raw_code"', '"compiled_code"', '"raw_sql"',
                                           '"compiled_sql"', '"macros": {\\n')):
                raise ValueError(f"Source-bearing fields remain in {path}")
            if check:
                if json.loads(raw) != doc:
                    raise ValueError(f"Not sanitized: {path}")
            else:
                path.write_text(raw)
                registry["sha256"][f"compiler/zero-manifests/{case_id}/{side}/manifest.json"] = (
                    hashlib.sha256(raw.encode()).hexdigest())
                changed += 1
    if len(registry["sha256"]) != original_count:
        raise ValueError("Checksum inventory entry count changed")
    if not check:
        HASHES.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
    print(f"Validated {len(UNLICENSED)} source-free project pairs, {len(UNLICENSED)*2} manifests; updated {changed}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    run(check=parser.parse_args().check)
