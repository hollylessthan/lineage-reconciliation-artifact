# protocol-v1: frozen protocol for paper runs

Frozen protocol reference: Git tag `protocol-v1` marks the exact commit. Paper evidence is only what workflow `protocol-v1 paper runs` produced at that commit (recorded as `github_sha` in every result). Development runs before the tag are pilot evidence only.

## What is frozen

Everything in the tagged tree, in particular:

- **Relations and contracts:** `scripts/metamorphic_core.py` (MR1a-c, MR2a-b, MR3, MR4a-b, MR5, MR5i, MR7, MR9a-c) and the per-path contracts in the adapters, matching the frozen contract assignments (see the manuscript contract table).
- **Harness and adapters:** `scripts/metamorphic_native.py`, `scripts/engines.py`, `scripts/round2b.py`, `scripts/real_revisions.py`, `scripts/export_revision_manifests.py`.
- **Integrity gate** (fails a path, never reclassifies a verdict): calibration present with 0 false alarms; every history executed and stabilized; no relation or control `not_testable`/`control_failed`; every single-step fresh state matches the authored oracle (partial OpenLineage run patterns under test exempt).
- **Fixtures, versions and servers:** pinned requirement files, compose files, container image tags, and the 9 frozen real revision pairs in `docs/compiler-candidates.json`.

No file in that list changes after the tag. Any change requires `protocol-v2` and a complete rerun.

## Runs

Three repetitions (`-p1-rep1..3`), each on fresh disposable servers, of every path defined by:

| Workflow | Paths |
|---|---|
| `metamorphic.yml` | DataHub 1.8.0: dbt, PostgreSQL views, views incremental, OpenLineage (UPSERT); OpenMetadata 2.0.7: dbt override, dbt default, views override, OpenLineage; Marquez 0.51.1; real-revision replay (DataHub dbt) |
| `round2-engines.yml` | DataHub 1.8.0 and OpenMetadata 2.0.7 views on MySQL, MariaDB, ClickHouse, Trino, SQL Server |
| `round2b.yml` | DataHub 1.5.0: dbt, views, OpenLineage (UPSERT); DataHub OpenLineage `usePatch=true` on 1.5.0 and 1.8.0; OpenMetadata 1.13.6: dbt override, views override, OpenLineage; Open Data Discovery 0.29.0 via odd-dbt |

Every path is run, including two that were inadmissible in development (DataHub SQL Server views; DataHub 1.5.0 UPSERT OpenLineage). They are reported, not dropped.

## Analysis rules (fixed before the runs)

1. A path-repetition is **admissible** only if its integrity gate passed. Inadmissible repetitions are reported with the gate reason and contribute no verdicts.
2. A relation outcome is **replicated** if it is identical in all three admissible repetitions of that path. It is **unstable** if repetitions disagree; unstable outcomes are reported and not counted as findings.
3. A path with fewer than three admissible repetitions is reported as **partially replicated** (k/3); its outcomes are not headline findings.
4. **Findings** are replicated `violation` verdicts under the path's contract. They are grouped by root cause (inspected code path) before counting; the count of root causes, not of affected paths, is the headline.
5. Characterization outcomes (`differs`) and documented deviations are reported separately and never counted as defects.
6. Real-revision replay is secondary evidence: per-pair MR1 forward/reverse, sanity checks, and how many pairs completed.
7. Pre-registered predictions P1-P9 are scored against replicated outcomes only.

## Not part of protocol-v1

Upstream issue filing, frequency mining (round 4), real OpenLineage producers (round 3), and Apache Atlas.
