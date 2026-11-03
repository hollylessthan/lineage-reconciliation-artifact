#!/usr/bin/env python3
"""Offline verification of six post-frozen zero-dependency revision replays."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "evidence/replay/datahub.json", ROOT / "evidence/replay/openmetadata.json"]

def states_equal(left, right):
    if left is None or right is None:
        raise ValueError("missing replay state")
    return {tuple(x) for x in left} == {tuple(x) for x in right}


def verify(paths=FILES):
    jobs = []
    for path in paths:
        doc = json.loads(path.read_text())
        assert doc["schema"] == "zero-dependency-replay/v1"
        jobs.extend(doc["jobs"])
    assert len(jobs) == 6, len(jobs)
    observed = {}
    for job in jobs:
        product = job["product"]
        assert product in ("DataHub", "OpenMetadata")
        cases = job["cases"]
        assert len(cases) == (6 if product == "DataHub" else 12), (product, len(cases))
        per_mode = {}
        for c in cases:
            case_id = c["id"]
            assert case_id.startswith("zero")
            mode = "replace" if product == "DataHub" or c.get("override") is True else "additive"
            key = (product, mode, case_id)
            assert key not in per_mode, key
            per_mode[key] = c
            assert c["sanity_before"] is True and c["sanity_after"] is True
            assert c["removed"] and not c["added"]
            assert c["MR1_reverse"] == ("holds" if states_equal(c["states"].get("after/before"), c["states"].get("before")) else "violation")
            states = c["states"]
            assert states.get("after") == [], (key, states)
            assert states.get("before"), key
            assert states.get("before/after"), key
            assert c["MR1_forward"] == ("holds" if states_equal(c["states"].get("before/after"), c["states"].get("after")) else "violation")
            assert c["repository"] and len(c["commit"]) == 40
            observed.setdefault(key, []).append(c)
        assert len(per_mode) == len(cases)
    assert len(observed) == 18, len(observed)
    assert all(len(v) == 3 for v in observed.values()), {str(k): len(v) for k,v in observed.items()}
    expected_ids = {f"zero{i:02d}" for i in range(6)}
    for product,mode in [("DataHub","replace"),("OpenMetadata","replace"),("OpenMetadata","additive")]:
        assert {k[2] for k in observed if k[:2] == (product,mode)} == expected_ids
    for key, reps in observed.items():
        assert len({(c["repository"], c["commit"], tuple(c["removed"])) for c in reps}) == 1, key
    return {"cases": 6, "products": 2, "mode_case_combinations": 18,
            "observations": 54, "repetitions": 3,
            "replacement_forward_violations": 12,
            "additive_forward_retentions": 6}

if __name__ == "__main__":
    print(json.dumps(verify(),indent=2))
