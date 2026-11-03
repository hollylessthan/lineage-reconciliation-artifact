# Refresh contract table and pre-registered predictions

This is a documentation and released-source review. **No native run was used to decide a contract.** Predictions below were written before any G2/G3 run.

## Contract classes

- **Replace**: a complete run re-states the target's current lineage; edges absent from the new input should disappear.
- **Additive**: new edges are added; absent edges may remain by design.
- **Undetermined**: neither documentation nor inspected source states which applies. Only contract-agnostic relations (MR2 idempotence) are checked.

A contract can come from the catalog (documentation, configuration description, released source) or from the input standard the path consumes (the OpenLineage spec for push paths).

## Contract table

| Family | Catalog / path (pinned) | Configuration | Contract | Evidence |
|---|---|---|---|---|
| dbt manifest | DataHub, acryl-datahub 1.7.0.19, dbt source, dbt-platform entity | default | **Replace** | `dbt_common.py:901-904`: `incremental_lineage` "emits incremental/patch lineage for non-dbt entities. When disabled, re-states lineage on each run." `dbt_common.py:4679` applies patching only to the target-platform sibling; the dbt node aspect is always upserted. |
| dbt manifest | OpenMetadata ingestion 2.0.7.0, dbt source | `overrideLineage: false` (default) | **Additive** | Additive default kept by [PR #24827](https://github.com/open-metadata/OpenMetadata/pull/24827); prior pilot observed retained `b` |
| dbt manifest | OpenMetadata ingestion 2.0.7.0, dbt source | `overrideLineage: true` | **Replace** | Option exists to replace stale dbt edges ([#18411](https://github.com/open-metadata/OpenMetadata/issues/18411)); `dbt/metadata.py:1307` passes the flag per edge; `sink/metadata_rest.py:613-658` deletes edges by source on the target before writing |
| SQL view | DataHub 1.7.0.19, postgres source | `incremental_lineage: false` (default) | **Replace** | `incremental_lineage_helper.py:252-256`: "When disabled, re-states lineage on each run." |
| SQL view | DataHub 1.7.0.19, postgres source | `incremental_lineage: true` | Additive | Same field: "emits lineage as incremental to existing lineage" |
| SQL view | OpenMetadata 2.0.7.0, postgres-lineage | `overrideViewLineage: true` | **Replace** | `lineage_processors.py:403`: the flag "deletes the existing view lineage of the entity an edge points at before writing it" |
| SQL view | OpenMetadata 2.0.7.0, postgres-lineage | `overrideViewLineage: false` | Undetermined | No documented replacement statement found |
| OpenLineage push | DataHub GMS v1.8.0, `/openapi/openlineage/api/v1/lineage` | server default `usePatch=false` | **Replace per event** (catalog); **Accumulative per run** (input standard) | `DatahubOpenlineageProperties.java:37` (`usePatch = false`); `DatahubJob.java:212-218`: in UPSERT mode "emitting the empty aspect is the only way to clear edges"; [OpenLineage run cycle](https://openlineage.io/docs/spec/run-cycle/): events for one run are accumulative and complete information comes from combining all events |
| OpenLineage push | OpenMetadata 2.0.7, `/v1/openlineage/lineage` | default settings | **Undetermined** (removal); documented COMPLETE-only filter | [API reference](https://github.com/open-metadata/OpenMetadata/blob/2.0.7-release/openmetadata-service/src/main/java/org/openmetadata/service/resources/lineage/OpenLineageResource.java) and [how-to](https://github.com/open-metadata/OpenMetadata/blob/2.0.7-release/openmetadata-spec/src/main/resources/json/schema/configuration/openLineageConfiguration.json) show the ingestion endpoint and define `eventTypeFilter` default `COMPLETE`, without documenting removal of existing edges |
| OpenLineage push | Marquez 0.51.1, `/api/v1/lineage` | default | **Replace per completed job version** | `JobVersionDao.java:216-235`, `upsertInputDatasetFor` marks earlier inputs non-current; `OpenLineageDao.java:371-400` explicitly marks inputs/outputs obsolete when an event carries none; [job versioning](https://openlineage.io/blog/explore-lineage-api/) derives versions from inputs/outputs |

## Gate decision

| Condition | Result |
|---|---|
| ≥3 ingestion families with a determinate contract on at least one catalog | **PASS**: dbt (DataHub, OpenMetadata override), SQL view (DataHub, OpenMetadata override), OpenLineage (DataHub, Marquez) |
| ≥2 families determinate on both DataHub and OpenMetadata | **PASS**: dbt and SQL view |
| Marquez feasible | **PASS for G2**: determinate contract, lightweight server (API + PostgreSQL). Docker Hub is unreachable from the authoring workspace, so it runs in GitHub Actions like the other catalogs |

**G1: PASS.**

## Added relation for the OpenLineage family

**MR9 Run accumulation.** Splitting one run's information across START/RUNNING/COMPLETE events must give the same current lineage as a single COMPLETE event carrying the union: `S([START{in}, COMPLETE{}]) = S([COMPLETE{in}])`. Contract source: the OpenLineage spec. A consumer that documents a narrower event filter (OpenMetadata's COMPLETE-only default) is classified as a **documented deviation**, not a defect.

## Pre-registered predictions (from source only)

Written before any G2/G3 run. Each will be marked confirmed, refuted, or not testable.

| ID | Path | Prediction | Relation | Source reason |
|---|---|---|---|---|
| P1 | DataHub postgres views, Replace | A view changed to have zero upstreams keeps its old lineage | MR1, MR3 | `sql_parsing_aggregator.py:1773-1774` returns without emitting when upstreams and fine-grained lineage are empty |
| P2 | OpenMetadata views, `overrideViewLineage: true` | Same as P1 | MR1, MR3 | Deletion is triggered by an edge request (`metadata_rest.py:624`); a view with no upstreams produces no request |
| P3 | DataHub OpenLineage, `usePatch=false` | A run whose COMPLETE event omits inputs already sent in START ends with no input edges | MR9 | UPSERT of an empty aspect per event (`DatahubJob.java:212-218`) conflicts with the accumulative spec |
| P4 | Marquez | MR1 and MR3 hold (explicit empty handling). MR9 outcome is uncertain: an event without inputs marks inputs obsolete (`OpenLineageDao.java:383`) but the completed version may relink run inputs | MR1, MR3, MR9 | Same lines |
| P5 | OpenMetadata OpenLineage | Changed job inputs leave old edges (Additive-like); MR9 fails by the documented COMPLETE-only filter | MR2, MR9 | Documented filter; removal undocumented |
| P6 | DataHub dbt, OpenMetadata dbt override | Known zero-dependency violation reproduces (positive control) | MR1, MR3 | Prior pilot |

P1 and P2 share the **empty-emission mechanism class** with the known dbt result. If confirmed, they count as new code-path violations of the same class and are reported that way, not as independent mechanisms.

## Limits

Source inspection covered the cited files only. DataHub server-side processing of the OpenLineage endpoint beyond the converter was not inspected. OpenMetadata server-side `deleteLineageBySource` semantics were not inspected; prior traces show multi-edge override writes ending correct, so per-edge deletion must be handled server-side or by ordering.
