"""Bounded Spark producer probe. Inspect generated events only, never inject synthetic events.

Requires Spark 3.5.x + compatible OpenLineage Spark listener JAR and file transport.
Provide JAR with --packages as documented in the workflow. Exit nonzero when no
OpenLineage events were produced.
"""
from pyspark.sql import SparkSession
from pathlib import Path
import json, os

out = Path(os.environ.get("OL_PROBE_DIR", "/tmp/ol-spark-events"))
out.mkdir(parents=True, exist_ok=True)
spark = SparkSession.builder.master("local[2]").appName("lineage-contract-spark-probe").getOrCreate()
try:
    base = Path("/tmp/ol-spark-probe-data")
    base.mkdir(exist_ok=True)
    spark.createDataFrame([(1,), (2,)], ["id"]).write.mode("overwrite").parquet(str(base / "a"))
    spark.createDataFrame([(3,), (4,)], ["id"]).write.mode("overwrite").parquet(str(base / "b"))
    a = spark.read.parquet(str(base / "a"))
    b = spark.read.parquet(str(base / "b"))
    a.unionByName(b).write.mode("overwrite").parquet(str(base / "out_ab"))
    a.write.mode("overwrite").parquet(str(base / "out_a"))
    spark.range(2).write.mode("overwrite").parquet(str(base / "out_empty"))
finally:
    spark.stop()

files = list(out.rglob("*.json")) + list(out.rglob("*.jsonl"))
events = []
for p in files:
    for line in p.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("eventType") in ("START", "COMPLETE", "FAIL", "RUNNING"):
            events.append(event)
summary = {}
for e in events:
    key = (e.get("job") or {}).get("name", "<unnamed>")
    summary.setdefault(key, []).append({
        "type": e.get("eventType"),
        "runId": (e.get("run") or {}).get("runId"),
        "inputs_present": "inputs" in e,
        "input_count": len(e.get("inputs") or []),
        "output_count": len(e.get("outputs") or []),
    })
print(json.dumps({"events": len(events), "jobs": summary}, indent=2))
if not events:
    raise SystemExit("NO GO: Spark generated no parsed OpenLineage events; do not infer producer semantics")
