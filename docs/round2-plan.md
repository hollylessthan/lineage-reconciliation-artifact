# Round 2 plan: breadth across connectors and catalogs

Follows [protocol-v1-results.md](protocol-v1-results.md). Goal: move from a short-paper result (3 violations, 2 mechanisms, 3 systems) toward a full-paper result by testing more connectors and more catalogs with the same relations. No new relations are added in this round, so the existing harness and gates carry over.

Upstream filing is deferred: findings are reported as contract violations with source and documentation references; filing is decided closer to submission.

## Order of work

| Step | Item | What | Why first / later |
|---|---|---|---|
| 2A | Connector breadth | Same relations on more SQL engines, both catalogs | Cheapest; reuses the view family |
| 2B | Catalog breadth | Older releases of DataHub/OpenMetadata; Apache Atlas; Open Data Discovery | Popular open-source catalogs; each needs a G1-style contract check first |
| 3 | Real OpenLineage producers | Airflow OpenLineage provider, Spark integration, replacing hand-written events | Strengthens F3; after 2A/2B |
| 4 | Frequency | Mine public dbt projects and view DDL histories for transitions to zero dependencies | Answers "how often does this happen"; independent of catalogs |

## 2A: connector breadth (SQL views)

**Correction to the earlier suggestion:** Snowflake, BigQuery and Redshift need paid cloud accounts and cannot run in this CI. They are excluded unless the author provides a sandbox account (not an employer account).

Engines that run as Docker containers in CI and have view-lineage support in both pinned clients (verified in installed source: DataHub `sql_common` view lineage; OpenMetadata `source/database/<engine>/lineage.py`):

| Engine | DataHub path | OpenMetadata path | Notes |
|---|---|---|---|
| MySQL 8 | `mysql` (sql_common) | `mysql` | Baseline |
| MariaDB | `mariadb` | `mariadb` | Separate dialect handling |
| ClickHouse | `clickhouse` | `clickhouse` | Has its own materialized-view handling in OpenMetadata (`_writes_into_view`) |
| Trino (memory/PostgreSQL catalog) | `trino` (sql_common) | `trino` | Cross-catalog naming |
| SQL Server (Developer edition image) | `mssql` | `mssql` | Separate view and stored-procedure lineage code |

**Expected outcome, stated honestly:** most engines share the code paths behind F1/F2, so the likely result is the **same mechanism across more connectors** (breadth of impact, useful for the paper's significance claim), not new mechanisms. Engines with their own lineage code (ClickHouse, SQL Server) are where a new mechanism is most likely.

Work: one `pg_view`-style fixture per engine, one adapter class per engine/catalog (recipe + identity mapping), one workflow job per catalog with engine services. Estimated 5 engines x 2 catalogs = 10 paths.

## 2B: catalog breadth

Each candidate first gets a G1-style contract entry from docs and released source. A candidate without a determinate contract is tested only with contract-agnostic relations (MR2, MR9) or dropped.

| Candidate | Status check (2026-11-01) | Families it could cover | Feasibility |
|---|---|---|---|
| Older DataHub and OpenMetadata releases (e.g. one prior minor release each) | Same projects | All three | **High**. Same harness; shows whether behavior regressed or was always present |
| Apache Atlas | Active (latest tag `release-2.6.0-rc4`, commits through 2026-10-30) | SQL views via the Hive hook; Process-entity lineage via REST | **Medium**: heavy stack (HBase/Solr/Kafka); community all-in-one Docker image exists. Hive hook needed for a native path |
| Open Data Discovery (ODD) Platform | Latest tag `v0.6.0-beta-2`; commits through 2026-09 | dbt via `odd-dbt` collector | **Medium**: beta; contract likely undocumented |
| Amundsen | Latest tag `v1.0.1`; commits through 2026-09 | dbt via databuilder | **Low priority**: lineage is a secondary feature |
| Egeria | Active (commits through 2026-10-31) | OpenLineage integration | **Low priority**: heavyweight; overlaps conformance work already cited |
| Unity Catalog OSS | v0.7.0 | none found | **Excluded**: no lineage API found in the OSS `api/` specification |

Recommended 2B scope: older DataHub/OpenMetadata releases first, then Apache Atlas, then ODD if time allows.

## Gate for round 2

Same G2 validity checks per new path (calibration, fresh-state oracle, positive control). A full-paper decision (G4) needs, beyond round 1:

- violations or confirmed holds on **at least 8 additional paths**, and
- **at least one new mechanism** beyond empty-emission and per-run accumulation, or evidence that one mechanism spans most connectors and multiple catalogs, and
- a frozen protocol rerun on fresh servers with repeats.

If round 2 only replicates F1/F2 on more connectors, the result still strengthens a short or industry paper (breadth of impact) but does not by itself justify a full research paper.

## Pre-registered round 2B predictions (written before any 2B run, 2026-11-01)

| ID | Path | Prediction | Source reason |
|---|---|---|---|
| P7 | DataHub OpenLineage, `usePatch=true` | **v1.5.0: MR9b fails** (START without datasets, then COMPLETE with them, loses the inputs). **v1.8.0: MR9b holds.** | v1.5.0 `DatahubJob` lacks the empty-PATCH guard that v1.8.0 adds; v1.8.0's comment says an all-empty early event otherwise creates an aspect a later PATCH cannot override. A known-fixed bug, used as a regression-sensitivity control |
| P8 | Open Data Discovery 0.29.0, odd-dbt | **MR1b holds**: a model with zero dependencies still emits its output edge, so its previous edges are deleted | `LineageServiceImpl.replaceLineagePaths` deletes by establisher taken from the payload's relations; `DbtLineageMapper` always adds the model's output |
| P9 | DataHub v1.5.0 views and dbt; OpenMetadata 1.13.6 views and dbt override | **MR1b fails**, as in the current releases | Same empty-emission code present in the inspected older sources |

Apache Atlas is not tested: the available image ships without the Hive hook, so no native path exists without building one.
