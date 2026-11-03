#!/usr/bin/env python3
"""Reproduce core protocol-v1 findings from sanitized frozen job instrumentation."""
import json
from pathlib import Path
from score_export import score, check_headline

ROOT = Path(__file__).resolve().parents[1]

def verify():
    parts = sorted((ROOT / "evidence/frozen").glob("part-*.json"))
    if len(parts) != 12:
        raise ValueError(f"expected 12 evidence parts, found {len(parts)}")
    jobs = []
    for path in parts:
        data = json.loads(path.read_text())
        if data.get("schema") != "frozen-instrumentation-export/v1":
            raise ValueError(f"invalid schema: {path}")
        if len(data.get("jobs", [])) != 5:
            raise ValueError(f"expected five job records: {path}")
        jobs.extend(data["jobs"])
    names = [j["name"] for j in jobs]
    if len(names) != 60 or len(set(names)) != 60:
        raise ValueError("incomplete or duplicate job inventory")
    result = score({"schema":"frozen-instrumentation-export/v1","jobs":jobs})
    check_headline(result)
    return result

if __name__ == "__main__":
    print(json.dumps(verify(),sort_keys=True,indent=2))
