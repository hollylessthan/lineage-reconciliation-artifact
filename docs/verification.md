# Artifact verification

These checks support the reported frozen findings; they do not substitute for a fresh live catalog replay.

## Direct independent examination

- Retrieved **60/60** original archived result ZIPs.
- Located **84/84** `metamorphic-results.json` records. All 84 identify the same frozen commit `58c995f32abdf23d3441cc2bbb7053f7de247ee3`.
- Located **three** `real-revision-results.json` files, with nine cases each: **27/27** records.
- Recomputed each real-revision forward and reverse MR1 equality using stored before, after and two-order lineage states. **0** label mismatches.
- Compared all 27 real-revision fresh before/after states with their separate stored expected-state oracles. **0** mismatches.
- All 27 real-revision sanity flags passed.
- Archived source ZIPs were inspected in a temporary workspace; unfiltered logs and private-run URLs are not copied into the public artifact.

These checks independently corroborate the nine frozen real-revision pairs. They do **not** refer to the six *post-frozen zero-dependency* pairs, which are separately exported and scored.

## Reproduction

The archive-based audit is in `scripts/audit_original_archives.py`. It takes the downloaded original ZIPs, counts the structured records, recalculates equality, checks case identity and fresh-state oracles, and records source ZIP SHA-256 hashes. This requires authorized access to obtain the 60 ZIPs, or an explicitly licensed and privacy-reviewed redistribution of those ZIPs.

## Frozen-export cross-check

An additional independently collected comparison of the original ZIP records against all 12 sanitized export parts found:

| Preserved field family | Original records | Curated export | Distinct record values | Canonical multiset fingerprint match |
|---|---:|---:|---:|---|
| Relation path/ID/verdict/observed A/B edges | 738 | 738 | 185 | Yes |
| History path/steps/edges/stability | 1,158 | 1,158 | 206 | Yes |

The fingerprints were computed independently from the original ZIPs and the curated GitHub export. The executable `scripts/reconcile_export.py` uses **exact Counter/multiset equality** of canonical JSON values instead of relying on the shorter fingerprints. This validates the preserved relation and history observations, **not** excluded raw logs, orchestration identifiers or arbitrary omitted fields. Re-execution with all 60 original ZIPs should be retained as an offline release verification step.


## Release-source and contract evidence

## Independently read from released tags

| Path | Fixed source reference | Confirmed detail | Scope |
|---|---|---|---|
| DataHub dbt, 1.8.0 | [dbt_common.py at v1.8.0](https://github.com/datahub-project/datahub/blob/v1.8.0/metadata-ingestion/src/datahub/ingestion/source/dbt/dbt_common.py), blob `ab5217c3edb171f1fd0479d33f278083dd31370d` | Contains `if not upstream_urns: return None` in model upstream lineage construction | Supports omission mechanism R3 |
| DataHub dbt, 1.5.0 | [dbt_common.py at v1.5.0](https://github.com/datahub-project/datahub/blob/v1.5.0/metadata-ingestion/src/datahub/ingestion/source/dbt/dbt_common.py), blob `ded5c878dc6e6ff57d81d370bca20d6865f1c975` | Same empty-upstreams early return | Supports R3 across both server release tags |
| DataHub SQL views, 1.8.0 | [incremental_lineage_helper.py at v1.8.0](https://github.com/datahub-project/datahub/blob/v1.8.0/metadata-ingestion/src/datahub/ingestion/api/incremental_lineage_helper.py), blob `e92675083e3f620bda27e30077e80e0b00859ac0` | `incremental_lineage` defaults to false and its description says disabled mode restates lineage on each run; enabled mode adds incrementally | Supports Replace/Additive distinction |
| DataHub SQL views, 1.5.0 | [incremental_lineage_helper.py at v1.5.0](https://github.com/datahub-project/datahub/blob/v1.5.0/metadata-ingestion/src/datahub/ingestion/api/incremental_lineage_helper.py), blob `47e7e4b276309e242123a25651db2bcf1b4451ee` | Contains the nonincremental branch and patch-conversion logic; this check alone is not a full view-parser contract audit | Partial version-specific support |
| OpenMetadata ingestion 2.0.7 | [metadata_rest.py at 2.0.7-release](https://github.com/open-metadata/OpenMetadata/blob/2.0.7-release/ingestion/src/metadata/ingestion/sink/metadata_rest.py), blob `60b5b8cd35047f6124d196fcaa925f0bb8f57131` | `write_override_lineage` conditionally deletes lineage by source before dispatching an edge write | Supports override deletion implementation for R2 |
| OpenMetadata ingestion 1.13.6 | [metadata_rest.py at 1.13.6-release](https://github.com/open-metadata/OpenMetadata/blob/1.13.6-release/ingestion/src/metadata/ingestion/sink/metadata_rest.py), blob `cc05381aa60de65f322baf75fc3e8656bc6521c3` | Also contains `write_override_lineage` and `delete_lineage_by_source` branch | Supports the older-release override implementation |

### Package provenance

The frozen run's job logs show the installed versions `acryl-datahub` 1.7.0.19 (24 job installs) and 1.5.0.19 (6), `openmetadata-ingestion` 2.0.7.0 (18) and 1.13.6.3 (3), `odd-dbt` 0.2.13 (3), and dbt-core 1.12.6 for the fixtures (dbt-core 1.7.18 for ODD; 1.10.23 for compiling the real-revision manifests). Each version has a single universal wheel. The wheels downloaded for this audit match the SHA-256 that PyPI publishes:

| Wheel | SHA-256 (matches PyPI) |
|---|---|
| `acryl_datahub-1.7.0.19-py3-none-any.whl` | `5a012b484a98a057f9e31d6276ae8c7cf221302fd29786d87fc3c28922976ac0` |
| `acryl_datahub-1.5.0.19-py3-none-any.whl` | `6e0600e853ffbad344c0402a6ffa8fc73fe73a4726f7d1d8e9b0a1d208ade02c` |
| `openmetadata_ingestion-2.0.7.0-py3-none-any.whl` | `0616cd7693ffc5c5ebd062e82303df170e429c00f99c9c0c384ed438995e9915` |
| `openmetadata_ingestion-1.13.6.3-py3-none-any.whl` | `2c872edbe885218200e84207e08d3e9701f0b54b982154f526e150e9725e72c9` |
| `odd_dbt-0.2.13-py3-none-any.whl` | `5aeb9ce9645600f5fffedb6993fdff7fa72993743f172210bb0d9a7de9cccc3f` |

This closes the wheel-to-source gap for the **ingestion clients**. R1 and R3 run in the client, so the checks below use the installed bytes directly rather than a server Git tag. The DataHub server tag (v1.8.0) and client wheel (1.7.0.19) are different artifacts; the paper should keep naming both, as Table 3 does.

### Ingestion-client code, from the installed wheels

| Claim | Package | File (SHA-256 of the file inside the wheel) | Finding |
|---|---|---|---|
| R1 | acryl-datahub 1.7.0.19 | `datahub/sql_parsing/sql_parsing_aggregator.py` (`101dc280d0cae95c28723b25c15730067beb0f36135d1e46996aba8e628003a7`) | Lines 1773-1774: `if not upstream_aspect.upstreams and not upstream_aspect.fineGrainedLineages: return` in `_gen_lineage_for_downstream` |
| R1 | acryl-datahub 1.5.0.19 | same file (`b5d79cb128232ba0df50dadcdf9cde101b5449539cb1bdb38f642530ad97c78f`) | Same early return, lines 1578-1579 |
| R3 | acryl-datahub 1.7.0.19 | `datahub/ingestion/source/dbt/dbt_common.py` (`6db07e4892377a1f5c4ec3e176a23aa13b2ad34353d2176974afc9dc66d9dc0c`) | Lines 5566-5567 `if not upstream_urns: return None`; caller appends the aspect only `if upstream_lineage_class:` (line 4250) |
| R3 | acryl-datahub 1.5.0.19 | same file (`f0d6180bbecaddc8df8bba4667a000057963e3d3189e0ea5263d984bf9a88d9a`) | Same, lines 3155-3156; caller guard at line 2326 |
| View contract | acryl-datahub 1.7.0.19 | `datahub/ingestion/api/incremental_lineage_helper.py` (`b02f78863fae418ffb35b86b67a2adf301bd0b662299b95c33c8733f6e6b272a`) | `incremental_lineage: bool = Field(default=False, description="When enabled, emits lineage as incremental ... When disabled, re-states lineage on each run.")` |
| View contract | acryl-datahub 1.5.0.19 | same file (`edae854c9feecf8104252d6f3ed6d80762af365719077a72dbcfc52b19918929`) | Same default and description (lines 174-178); `auto_incremental_lineage` returns the stream unchanged when disabled |
| R2 (dbt and views) | openmetadata-ingestion 2.0.7.0 | `metadata/ingestion/sink/metadata_rest.py` (`8ae736cc9c92358ac6ef673dc9f05919e9ead51f560df024b63dc5159ca93611`) | `write_override_lineage` (line 613): deletion by source happens only inside this per-request writer (line 624 onward) |
| R2 (dbt and views) | openmetadata-ingestion 1.13.6.3 | same file (`46ecac01c7bdc7cdeacfc9afc5d5afbf123013e288ede642429fee3cb4297703`) | `write_override_lineage` (line 589): same per-request deletion by source |
| View override gate | openmetadata-ingestion 2.0.7.0 | `metadata/ingestion/source/database/lineage_processors.py` (`c5b360c9262bbf35cafa8e2ae5d699ddebe4067d33474d9926fd7a867bd44779`) | `override_lineage=(overrideViewLineage and _writes_into_view(...))` (line 469): the flag rides on each emitted edge request |
| View override gate | openmetadata-ingestion 1.13.6.3 | same file (`dc15d10b6dcc32f73c3d46725375fe0377a6fb02195bdb8e2d2f8a29a97ef931`) | `override_lineage=overrideViewLineage` (line 387), also per edge request; no `_writes_into_view` refinement in this release |
| dbt default (Additive) | openmetadata-ingestion 2.0.7.0 | `metadata/generated/schema/metadataIngestion/dbtPipeline.py` (`9ee30c093e8b1253fdffb4e521250ace866d985c70f4638709ff43e1ef8d9761`) | `overrideLineage: ... = False` |
| dbt default (Additive) | openmetadata-ingestion 1.13.6.3 | same file (`e14d84cae8fa51b9437573b9430e40f7dccabaebbd60fee5ddcbb828d857ba75`) | `overrideLineage: ... = False` |
| ODD collector | odd-dbt 0.2.13 | `odd_dbt/mapper/lineage.py` (`842bfe02fe1001d399afc5cae1f2b94132fc05e791ce02ffcd8c177035032e19`) | `DbtLineageMapper.map` emits an entity for every model node, adding inputs only for declared upstreams, so a zero-upstream model is still sent |

### Server-side code, at the deployed release tags

Shallow clones of each tag; commit and Git blob IDs pin the bytes.

| Claim | Release tag (commit) | File (blob) | Finding |
|---|---|---|---|
| DataHub OpenLineage default mode | `v1.8.0` (`faab576d96cbdb27b8344a755e0bc0f42fdc9c15`) | `metadata-service/openapi-servlet/.../DatahubOpenlineageProperties.java` (`92d8391de54c762362be3874df48bc6bdc55af3f`) | `private boolean usePatch = false;` |
| R4 | `v1.8.0` | `metadata-integration/java/openlineage-converter/.../DatahubJob.java` (`58b8a187d4267960f7e61641aad04f33e37b62b0`) | `generateDataJobInputOutputMcp`: comment "emitting the empty aspect is the only way to clear edges"; empty-PATCH skip guarded by `isUsePatch()` |
| DataHub OpenLineage default mode | `v1.5.0` (`7f3833ba1334d8cd208b09c87a9eddccffc6c6ca`) | `DatahubOpenlineageProperties.java` (`f960f3ca048090a4a7ac005b246cd93707c7e01d`) | `usePatch = false` |
| P7 premise | `v1.5.0` | `DatahubJob.java` (`e2aa2c3a04c4067a53b3b6a051d0be1dd8f05a92`) | No empty-PATCH skip guard (present in v1.8.0); PATCH branch requires a non-empty set. P7's source premise holds; the refuted part is its behavioral prediction |
| OpenMetadata COMPLETE-only filter | `2.0.7-release` (`744c5236bf840e131f091614450a7e892f877382`) | `openmetadata-service/.../openlineage/OpenLineageMapper.java` (`b5018367913d1f8b07b1a890ffd80810d3db7e32`) | Without a configured `eventTypeFilter`, `allowedEventTypes = Set.of("COMPLETE")`; `shouldProcessEvent` drops others. Resource (`9375dabbe3aa73ff64f45458d3c7e3bf19d01294`) documents "Only COMPLETE events are processed by default." |
| OpenMetadata COMPLETE-only filter | `1.13.6-release` (`e9ba578333a244285afa2ea50be4d70ba49deb77`) | `OpenLineageMapper.java` (`459d295bbd8cd5491def5f39ad8391ce080fd3ab`) | Same default; same resource blob as 2.0.7 |
| Marquez contract | `0.51.1` (`27a4a1357d9078bc4e6738524dfe5ba9d77aa2df`) | `api/src/main/java/marquez/db/OpenLineageDao.java` (`f2d1cd5c222bef0fd5e6c5e177efc96693709444`) | When an event's inputs are null or empty (and it is not a terminal streaming event without datasets), `markInputOrOutputDatasetAsPreviousFor(job, INPUT)` marks earlier inputs as previous (lines 372-383) |
| ODD contract | `0.29.0` (`f12b8fbc25357608666eb998913c9668a8d17b1b`) | `odd-platform-api/.../service/LineageServiceImpl.java` (`311bc2139178702b429bf4a00df9f3fbd31e786f`) | `replaceLineagePaths`: `batchDeleteByEstablisherOddrn(establishers)` then `batchInsertLineages` |

### OpenLineage standard, pinned

At OpenLineage release `1.27.0` (`938b4280d3f14e368b2aceefe07e2ff468e308de`, the client version used by the Airflow and Spark probes), `spec/OpenLineage.json` (blob `58167f71407add7734810cda9943b39b83c89aa2`) has `$id` `https://openlineage.io/spec/2-0-2/OpenLineage.json`, the schema the controlled events declare. Its `website/docs/spec/run-cycle.md` (blob `93c82bc50df5a8ecd038b01249d91aea3c004c98`) states: "We assume events describing a single run are **accumulative**".

**Paper implication.** The two further statements the manuscript quotes in Section III, that consumers "need to combine all events for a specific run" and the `eventCompleteness` complete-snapshot option, come from the current documentation (1.55.0), not from 1.27.0. Recommended: cite the pinned 1.27.0 sentence as the basis for MR9, and present the later wording as a subsequent clarification. The MR9 basis is unchanged; only the citation needs pinning.

### Image digests pulled by the frozen run

From the job logs: `postgres:16.6` `sha256:557fea37a744d5f4c8faab304b0a90858b53ab119735a88c131fd19dab802f36`; `postgres:14` `sha256:a26d06e6878f114ab53aace021fd9c599b498cca4c5ba2c18b34aee472f20148`; `mysql:8.4.6` `sha256:869218921e61d6c3c89820955d63cca42971f0e3e6c1e2792247bbd944ebc6e9`; `mariadb:11.4.8` `sha256:bc474f00629f0123c10f9e1bca193a45d18af15a274cf0656acda64f1086c3b6`; `clickhouse/clickhouse-server:24.8` `sha256:1ffa82edee000a42c09313bd9f1293d94c570aee74babc1b3ca9983a35fa597b`; `trinodb/trino:476` `sha256:00125e40d063bc4816d165482f6044872b18b56026fb959d3b28ce1f96ffbbee`; `mcr.microsoft.com/mssql/server:2022-latest` `sha256:cf8f0ab2ebe61feec2eed2629061a07d247f791c2a8ddda74a4ac9f06a291718` (floating tag; this digest is what ran); `marquezproject/marquez:0.51.1` `sha256:0721c976cff17d8b14f7949d85d6dac9c7ea37cb9fe857caa19833730fcb1a50`; `ghcr.io/opendatadiscovery/odd-platform:0.29.0` `sha256:3b61b3f2d3c1cdb36eb8dab95c1bc17666eafff87c936512e2381ad4e46ec7f5`. DataHub and OpenMetadata images are pulled through Docker Compose, whose output in these logs does not print digests.

### Server builds that actually ran

Read from the frozen run's saved results (`server-config.json`, `server-version.json`, `images.json`, `image.json`) by an original one-time provenance check (run 41391600370; workflow source not distributed), because Docker Compose did not print image digests to the job logs. Every saved file in every repetition agrees:

| Server | Jobs (×3 repetitions) | Reported build | Equals release tag commit |
|---|---|---|---|
| DataHub v1.8.0 | dbt and PostgreSQL views, real-revision replay, MySQL, MariaDB, ClickHouse, Trino, SQL Server views (8 jobs) | `faab576d96cbdb27b8344a755e0bc0f42fdc9c15` | `v1.8.0` |
| DataHub v1.5.0 | older-release job | `7f3833ba1334d8cd208b09c87a9eddccffc6c6ca` | `v1.5.0` |
| OpenMetadata 2.0.7 | dbt, PostgreSQL views, OpenLineage; MySQL, MariaDB, ClickHouse, Trino, SQL Server views (6 jobs) | `744c5236bf840e131f091614450a7e892f877382` | `2.0.7-release` |
| OpenMetadata 1.13.6 | older-release job | `e9ba578333a244285afa2ea50be4d70ba49deb77` | `1.13.6-release` |

DataHub reports its build through `/config` (`versions."acryldata/datahub".commit`) and OpenMetadata through `/api/v1/system/version` (`revision`). The DataHub v1.8.0 jobs also recorded local image IDs: `acryldata/datahub-gms:v1.8.0` `sha256:6ab0d839068df00f7f9d2e5f7f704ee63cf0b5cdda30e844a559679513ab7618` and `acryldata/datahub-upgrade:v1.8.0` `sha256:b0fb64d69886696ab8ec115caac4ebda69b832055903255334bd33c428ba2c91`, identical in all six jobs that saved them. Marquez and ODD saved registry digests that match those in the log table above. So the server-side code that ran is the code read at the release tags, not only an image with the same tag name.


## Verification boundaries

The raw 60 frozen ZIP files were independently checked against the curated evidence and 27 original real-revision records. The full release should still undergo a clean-machine live Docker replay and privacy, licensing and dependency inspection. The source build table is backed by 57 saved provenance records in `evidence/native-run/server-builds.json` (24 DataHub configurations, 21 OpenMetadata versions, 6 image inventories, and 6 image repository digests). These records summarize captured source-run files, not freshly collected server configurations.

## Third-party source and licensing review

The six post-frozen compiler manifest pairs were generated from publicly accessible dbt projects, and **full dbt manifests contain source-derived fields including `raw_code`**. Their availability on GitHub does not by itself grant permission to redistribute every embedded source fragment. The artifact's own Apache-2.0 license does not override third-party rights.

| Source project | Repository-declared license at review | Release assessment |
|---|---|---|
| `Jam516/BundleBear` | MIT | Minimized to graph-only metadata; attribution and MIT notice retained |
| `synccomputingcode/databricks-tpcdi` | MIT | Minimized to graph-only metadata; attribution and MIT notice retained |
| `abduldjafar/elt-with-dagster` | No license declared | Minimized to graph-only metadata |
| `gip-inclusion/pilotage-airflow` | No license declared | Minimized to graph-only metadata |
| `winniemutai21/gz-dbt-repository` | No license declared | Minimized to graph-only metadata |
| `TherNgyn/Vietnam_economic_lakehouse` | No license declared | Minimized to graph-only metadata |

**Current mitigation:** All twelve manifests from six source projects have been reduced to declarative lineage metadata; four projects had no declared license and the remaining two had MIT-licensed original sources. The original source SQL, compiled SQL, descriptions, macros, and other source-bearing fields are not included in the current files. `scripts/sanitize_unlicensed_manifests.py --check` checks the four no-license pairs, while the release inventory contains graph-only versions of all six pairs and its declared graph against the accepted case index. The original repository/commit references remain as provenance. The graph-only files are **not** ingested directly. The tested protocol uses complete dbt manifests generated from synthetic SQL and the preserved dependency graph; the fresh-runner smoke test was completed in the clean repository as [run 41570439429](https://github.com/hollylessthan/lineage-reconciliation-artifact/actions/runs/41570439429). This new repository uses an independent clean history; historical unsanitized commits exist only in the separate private development repository. GitHub license metadata may differ at each original pinned commit.

## Local privacy and link checks

The offline CI runs `scripts/release_audit.py`, which checks available repository text for high-confidence credential patterns, direct private-study URLs, broken relative Markdown links and Python parse errors. The scan passes on the current branch. This is a scoped screening, not proof that raw manifests contain no third-party confidential material. All documentation citations have been checked against source pages or pinned source files, but this review does not crawl arbitrary URLs in code.

## Fresh-runner bounded lineage replay

[GitHub Actions run 41570439429](https://github.com/hollylessthan/lineage-reconciliation-artifact/actions/runs/41570439429) in the clean release repository executed one reconstructed zero-dependency revision pair (`zero01`) with fully synthetic SQL generated by `scripts/generate_synthetic_dbt_manifest.py`, on fresh DataHub v1.8.0 and OpenMetadata 2.0.7 Docker deployments. For both systems, the logged `sanity_before` and `sanity_after` checks were `true`; MR1 forward reported `violation` and reverse reported `holds`. The workflow asserts the baseline sanity checks and testability, not that a violation is a test failure. This is a **single-case smoke test**, not an independent replay of the complete frozen matrix and not a claim that the original third-party SQL was ingested. The retained minimized source manifests are graph records; the schema-valid replay manifests are created from independently written synthetic SQL at test time.

## External documentation link check

The two formerly inaccessible OpenMetadata documentation links were replaced with upstream files pinned to `2.0.7-release`: [OpenLineageResource.java](https://github.com/open-metadata/OpenMetadata/blob/2.0.7-release/openmetadata-service/src/main/java/org/openmetadata/service/resources/lineage/OpenLineageResource.java) documents the OpenLineage API and its default COMPLETE-only processing, and [openLineageConfiguration.json](https://github.com/open-metadata/OpenMetadata/blob/2.0.7-release/openmetadata-spec/src/main/resources/json/schema/configuration/openLineageConfiguration.json) defines `eventTypeFilter`, default `["COMPLETE"]`. Both pinned source files were retrieved directly. Previously checked references include six pinned GitHub source files, an OpenMetadata issue and PR, and official OpenLineage specifications. Only citation links have been reviewed; this is not an exhaustive crawl of URLs embedded in executable files.

## Clean repository import and attribution

The public-release candidate starts from a fresh repository, without the private development history. All twelve third-party compiler manifests were reduced to graph-only metadata, and the ephemeral Spark `driverHost` and web UI hostname were replaced with a non-routable placeholder. The record-level hashes are updated in `evidence/import/SHA256.json`. `THIRD_PARTY_NOTICES.md` reproduces pinned MIT notices for the two permissively licensed source repositories and credits upstream Apache-2.0 Docker Compose material. The clean-repository live run was completed in [Actions run 41570439429](https://github.com/hollylessthan/lineage-reconciliation-artifact/actions/runs/41570439429), with both catalog jobs and lineage assertions passing.

## Final release audit scope

The source/rights audit confirms that all 12 exported compiler manifests contain only declarative graph and model identifiers; no original SQL or macro bodies are distributed. The four sources without declared licenses have been minimized; the two MIT-licensed sources retain attribution and full MIT license texts in `THIRD_PARTY_NOTICES.md`. The DataHub and OpenMetadata-derived Compose configurations are acknowledged with their Apache-2.0 provenance, and the repository retains its license text. The 26 Spark events have a non-routable, anonymized runner hostname. The current release tree excludes archived private ZIPs and the private development Git history.

Automated checks include `scripts/release_audit.py`, `scripts/verify_evidence_hashes.py`, and `scripts/hash_snapshot.py --check` against all tracked release files other than the inventory itself. SHA-256 hashes and a clean Git commit identify the reviewed source snapshot. This is a technical/privacy and attribution review, not a legal opinion or a guarantee that every third-party source author has waived rights.
