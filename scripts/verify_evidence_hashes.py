#!/usr/bin/env python3
"""Validate public evidence checksums, graph-only manifests and Spark redaction."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
manifest = json.loads((EVIDENCE / "import/SHA256.json").read_text())
entries = manifest["sha256"]
assert len(entries) == 16, "Unexpected reviewed evidence inventory size"
for rel, expected in sorted(entries.items()):
    path = EVIDENCE / ("probes/" + rel if rel.startswith("spark/") else rel)
    assert path.is_file(), f"Missing evidence: {rel}"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == expected, f"SHA256 mismatch: {rel}"
index = json.loads((EVIDENCE / "compiler/zero-manifests/index.json").read_text())
assert len(index) == 6
for case in index:
    for side in ("before", "after"):
        doc = json.loads((EVIDENCE / "compiler/zero-manifests" / case["id"] / side / "manifest.json").read_text())
        target = doc["nodes"][case["node"]["unique_id"]]
        assert sorted(target.get("depends_on", {}).get("nodes", [])) == sorted(case[f"{side}_deps"]), (case["id"], side)
        assert not doc.get("macros"), (case["id"], "macros remain")
        assert not doc.get("docs"), (case["id"], "docs remain")
        for node in list(doc.get("nodes", {}).values()) + list(doc.get("sources", {}).values()):
            for key in ("raw_code", "compiled_code", "raw_sql", "compiled_sql", "description", "checksum", "doc_blocks"):
                assert key not in node, (case["id"], key)
spark=(EVIDENCE / "probes/spark/events.jsonl").read_text()
assert "runnervm" not in spark.lower()
assert len([json.loads(line) for line in spark.splitlines() if line.strip()]) == 26
print("PASS: 16 evidence checksums, 12 graph-only manifests, 26 redacted Spark events")
