# Lineage Reconciliation Research Artifact

Companion artifact for *When Lineage Goes Stale: Contract-Conditioned Metamorphic Testing of Metadata Catalog Ingestion*.

This repository provides preserved experimental observations, scripts to reproduce the reported analysis, and a fresh-environment Docker smoke test for a representative lineage-removal scenario in DataHub and OpenMetadata.

## Reproduce the reported results

With Python 3.9 or later, clone the repository and run these standard-library-only checks from its root:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/verify_summary.py
python scripts/verify_frozen.py
python scripts/verify_replay.py
python scripts/generate_matrix.py --check
python scripts/verify_evidence_hashes.py
python scripts/release_audit.py
```

The verifiers recompute relation verdicts and summary measures from recorded lineage observations, rather than accepting stored labels. Expected results include 28 paths (26 admissible and 2 excluded), 17 final-dependency violation cells, 2 controlled UPSERT run-event violation cells, 4 documented OpenMetadata deviations, and 8 avoided counterfactual alarms. The six post-frozen dbt revisions are checked separately.

## Navigate the artifact

| Location | Purpose |
|---|---|
| `docs/protocol-v1.md`, `docs/contract-and-predictions.md`, `docs/round2-plan.md` | Frozen protocol, ingestion contracts, and predictions |
| `docs/protocol-v1-results.md`, `docs/protocol-v1-ablation.md` | Results and ablation |
| `evidence/frozen/part-*.json` | Preserved observations from 60 workflow jobs, covering 84 path/repetition records |
| `scripts/metamorphic_core.py`, `tests/`, `fixtures/` | Relation definitions and executable tests |
| `evidence/replay/`, `scripts/verify_replay.py`, `docs/zero-dependency-replay.md` | Six-revision post-frozen dbt replay evidence and analysis |
| `evidence/compiler/`, `evidence/import/SHA256.json` | Compiler triage and 12 graph-only before/after manifests with evidence hashes |
| `evidence/probes/spark/events.jsonl` | 26 preserved Spark OpenLineage events, with temporary runner hostname redacted |
| `evidence/native-run/` | Container, runtime and 57 server-build provenance records |
| `paper/tables/path-matrix.json`, `paper/tables/path-matrix.tex` | Machine-readable matrix and corresponding manuscript table |
| `docs/verification.md`, `THIRD_PARTY_NOTICES.md` | Archive reconciliation, version checks, reproducibility scope and third-party notices |

The frozen source identifier is `58c995f32abdf23d3441cc2bbb7053f7de247ee3` (`protocol-v1`). It identifies an original private experiment snapshot, not a publicly resolvable Git commit. The exported evidence and integrity checks in this repository are the reviewer-accessible record.

## Optional live Docker validation

The [clean-repository smoke-test run](https://github.com/hollylessthan/lineage-reconciliation-artifact/actions/runs/41570439429) deployed fresh DataHub v1.8.0 and OpenMetadata 2.0.7 instances and evaluated the source-free synthetic dbt revision pair `zero01`. Both systems passed their before/after lineage oracle checks, reproduced an MR1 forward stale-lineage violation, and satisfied the reverse relation.

To repeat this validation, use **Actions → Sanitized dbt manifest live smoke test → Run workflow** on `main`, or inspect `.github/workflows/sanitized-manifest-smoke.yml` for the exact dependencies, container configuration, and commands. The smoke test is manually triggered to avoid accidental Docker runner costs. The other manual workflows under `.github/workflows/` document the broader experiment configurations, which require Docker Engine, Compose, and their specified Python dependencies.

## Evidence integrity and reuse

The 12 exported third-party dbt manifests retain declarative model identities and dependency graphs rather than original SQL or macros. The live smoke test generates complete dbt manifests from independently written synthetic SQL. The original private ZIP archives and development Git history are not distributed.

Run `python scripts/verify_evidence_hashes.py` to validate the imported evidence checksums. Run `python scripts/hash_snapshot.py` to generate a SHA-256 inventory of tracked release files; if `docs/SNAPSHOT_SHA256.json` is present, run `python scripts/hash_snapshot.py --check` to verify it. The inventory excludes itself to avoid a self-reference. See `docs/verification.md` for audit methods and the distinction between offline analysis reproduction and representative live validation, and `THIRD_PARTY_NOTICES.md` for attribution.
