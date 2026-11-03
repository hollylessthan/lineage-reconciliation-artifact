#!/usr/bin/env python3
"""Check headline figures against exported summaries, not independent raw reruns."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
rows = []
for line in (root / "paper/tables/path-matrix.tex").read_text().splitlines():
    if not line.startswith(("DataHub ", "OpenMetadata ", "Marquez ", "ODD ")):
        continue
    fields = [part.strip().rstrip(chr(92)).strip() for part in line.split("&")]
    excluded = "X (inadmissible" in line
    rows.append((fields[0], fields[2:] if not excluded else [], excluded))
assert len(rows) == 28
assert sum(not excluded for _, _, excluded in rows) == 26
assert sum(excluded for _, _, excluded in rows) == 2
assert sum(value == "V" for _, cells, _ in rows for value in cells) == 19
assert sum(cells[1] == "V" for _, cells, excluded in rows if not excluded) == 17
assert sum(sum(c == "V" for c in cells[11:]) for _, cells, _ in rows) == 2

ablation = (root / "docs/protocol-v1-ablation.md").read_text()
assert sum("alarm/alarm/alarm" in line for line in ablation.splitlines() if line.startswith("| ")) == 8
data = json.loads((root / "evidence/probes/dbt-history-mining.json").read_text())
s = data["summary"]
assert (s["repos_cloned"], s["repos_active"], s["repos_with_to_zero_strict"],
        s["totals"]["to_zero_strict"], len(data["repos"])) == (249, 79, 11, 36, 250)
print("PASS: 28 paths, 26 admissible; 17 final-dependency and 2 event V cells;")
print("      8 counterfactual alarms; 249 scanned, 79 active, 36 strict transitions")
