# Real zero-dependency revisions: compile check and replay

Run 41383602363 (private development run; logs not distributed), workflow `.github/workflows/zero-dep-replay.yml`. Outside protocol-v1; a confirmation run after the frozen measurement.

## Compile check (`scripts/compile_check_zero_deps.py`, dbt-core 1.10, `dbt parse` only)

Input: the 36 strict to-zero events of the item-4 mining probe in 11 active repositories. techvaquero/dbtpcdi and mayurjainf007/dbtDemo list the same 12 events (copied history), so 24 distinct events in 10 histories.

| Result | Events |
|---|---|
| Confirmed: identity kept, compiled `depends_on.nodes` nonempty to empty | 6 |
| Model identity changed between revisions | 1 |
| Could not be parsed with offline profiles | 17 |
| Duplicate history (not re-run) | 12 events, 1 repository |

Confirmed pairs (one per repository): Jam516/BundleBear `21ae90a` (2 deps removed), abduldjafar/elt-with-dagster `8e3b50b` (1), synccomputingcode/databricks-tpcdi `7d60338` (2), gip-inclusion/pilotage-airflow `74c9022` (1), winniemutai21/gz-dbt-repository `0c9aefa` (2), TherNgyn/Vietnam_economic_lakehouse `6d36bf0` (8).

## Replay (3 repetitions, fresh servers)

| Path | Contract | Forward (drops last dependency) | Reverse (adds) | Fresh-state sanity |
|---|---|---|---|---|
| DataHub 1.8.0 dbt (`real_revisions.py`) | Replace | 6/6 violation, 3/3 reps | 6/6 holds | pass |
| OpenMetadata 2.0.7 dbt, `overrideLineage: true` (`real_revisions_om.py --override`) | Replace | 6/6 violation, 3/3 reps | 6/6 holds | pass |
| OpenMetadata 2.0.7 dbt, default | Additive | 6/6 retained (expected; not counted) | 6/6 holds | pass |

In every forward history the catalog keeps exactly the removed dependencies after the zero-dependency revision; fresh ingestion of the same revision shows none. This reproduces R3 (DataHub dbt) and R2 (OpenMetadata dbt override) on natural project revisions.

Limits: the six pairs are those that parsed offline, not a sample; OpenMetadata manifests are rebound to a disposable custom database (identities and `depends_on` unchanged); only the newer release lines were replayed.
