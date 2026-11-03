# BR6 / BR7 / BR8 implementation plan

Today the lakehouse half of BR6/7/8 is real: Kafka/Debezium land in bronze, Spark builds
silver (pseudonymised, schema-migrated), gold, `mart.org_progress`, `mart.video_heatmap`,
`mart.engagement_trend` and `gold.fct_content_sync`, with quality gates. The serving half
is not: `/api/admin/*` and `/api/instructor/{videos,courses,content}/*` compute from the
in-process demo (ADR 0008); the live overlays, telemetry fast path, content-sync service and
S3/OpenSearch/Redis content adapters are `NotImplementedError` stubs.

Decisions: full delivery like BR4/BR5 (real path -> persistent results -> scoped API ->
dashboards -> tests, benchmarks, runbook); live processing on Spark Structured Streaming
(as ADR 0009 did for BR5; new ADR 0013 supersedes ADR 0004's Flink choice for BR7/BR8
overlays); OpenSearch added for the BR8 search index.

Unlike BR4/BR5 (separate `br45` package, PostgreSQL serving), BR6/7/8 fill the existing
hexagonal stubs: the ports and use cases already exist, and the marts already live in the
lakehouse, so serving reads them through Trino rather than copying them to PostgreSQL.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Serve BR6/BR7/BR8 marts through Trino; scoped admin/instructor APIs; Admin + Instructor dashboards; mart quality gates | Done (see below) |
| 2 | Content sync service, S3/OpenSearch/Redis adapters, corpus reindex job | Done (see below) |
| 3 | Spark telemetry fast path + BR7/BR8 live overlays in Redis | Done (see below) |
| 4 | Benchmarks, implementation document, compose profile `br678` | Done: [implementation document](BR6_BR7_BR8_IMPLEMENTATION.md) |

Phase 1 delivered:
`contexts/analytics/application/ports.py` (read models + `AnalyticsMartReader`),
`contexts/analytics/infrastructure/trino_mart_reader.py`,
`entrypoints/api/routers/lakehouse.py` (+ `admin` role / `organisations` scope on the
shared token principal), `TrinoSettings`, warn gates `mart_org_progress_unresolved_dims`
and `mart_video_heatmap_unversioned`, Admin view and Instructor BR7/BR8 panels,
`tests/unit/test_lakehouse_api.py`, `tests/integration/test_lakehouse_marts.py`
(marker `spark`: reader SQL on real Delta tables from `warehouse/ddl`, no docker) and
`apps/web/tests/br678.spec.ts`. Verified locally against a full warehouse build
(35-day seed), then on the docker stack with real Trino (2026-11-02): same results.

Phase 2 delivered (ADR 0013): `SyncContentChange` + `domain/sync_policy.py` (CDC-safe
idempotency), `SubmitContentVersion` (write side), adapters `s3_document_store.py`,
`redis_cache.py`, `opensearch_index.py`, `hashing_embedder.py`, `postgres_content_catalog.py`,
`debezium_content_change.py`; `edu service content-sync`, `edu content seed-corpus |
ensure-index | register-cdc`, Spark `edu batch content-reindex` (-> `silver.content_chunks`);
`routers/content.py`; Instructor content sync + search panel; compose profile `br678`
(`opensearch`, `content-init`, `content-sync`). Fixed a chunker defect that dropped every
section shorter than 64 words (about two thirds of each transcript).
Tests: `test_content_sync.py` (moto S3, fakeredis), `test_opensearch_index.py` (fake client),
`test_content_api.py` (POST -> CDC record -> real service handler -> API), Spark
`test_content_reindex_job.py`, browser `br678.spec.ts`; against real services
`test_opensearch_real.py` and `test_postgres_content_catalog.py` (marker `integration`).

Verified on the docker stack (2026-11-02, Colima, 6 CPU / 10 GB): Debezium snapshot of the
8 seeded documents synced, 8 + 8 content events emitted; publish -> searchable through real
PostgreSQL, MinIO, Debezium, Kafka, Redis and OpenSearch: median 0.51 s, p90 0.96 s, max
1.00 s over 20 publishes (sync processing 25-70 ms); CDC delete removed vectors + search
entry; all 3 browser tests pass. Fixed on the way: `in_sync` was reported before search
could see the version (real-time GET vs refresh), sync took ~2 s (`refresh=wait_for`),
the demo image lacked the LMS connector file, and one missing object aborted the whole
Spark reindex (now isolated per item, job exits 1 listing failures).

Phase 3 delivered (ADR 0014): `telemetry-live` Spark app (normalise -> learning events /
DLQ; BR7 per-second heatmap and BR8 daily engagement -> Redis, absolute values),
`ClockSkewPolicy`, `RedisLiveOverlay`, `CachedMartReader` (60 s), `live` blocks in the
heatmap/engagement APIs and UI, `edu telemetry simulate`, Trino memory bounds
(`infra/trino/jvm.config`, `config.properties`). Verified on the docker stack: overlays equal
the domain computation (parity test on real Kafka + Redis, incl. duplicates and full replay);
event -> API median 6.8 s / max 9.5 s over 10 rounds with no loss; 4 browser tests pass.
Found and fixed: future-dated client clocks advanced the watermark and silently dropped
everyone's live events; Trino OOM-killed under dashboard polling (heap 80 % of a 2 GB
container + uncached polling); `pull_policy: build` made every `docker compose run`
recreate MinIO.

Open: `demo/seed.py` (bronze seed) declares ~18 courses/videos that `infra/postgres/init.sql`
does not, so the lakehouse references content with no LMS row or transcript; the reindex
job reports them as failures.

## Dependencies and files

1. **Source path.** Reuse `public.*` LMS tables + the existing `lms-postgres-cdc` connector.
   Add a telemetry producer (`edu telemetry publish`, and the demo simulator gains a Kafka
   mode) writing `telemetry.events.raw.v1` with schema 1.0/1.1, late and malformed events.
   Seed command loads organisations/learners/courses/content into PostgreSQL and corpus
   bodies into MinIO `corpus/` (versioned bucket).
2. **Telemetry fast path (BR6).** `entrypoints/streaming/telemetry_normalization_job.py` on
   Spark: raw topic -> existing `NormalizeEvents` / `spark_normalizer` -> pseudonymised
   `telemetry.learning_events.v1` + `telemetry.events.dlq.v1`. Bronze/silver landing stays as is.
3. **Live overlays (BR7, BR8).** One Spark Structured Streaming app reading
   `telemetry.learning_events.v1`, event-time watermark 5 min, checkpoints in MinIO:
   * BR7: per (content_id, version, second, 5-min window) play/pause/seek counts ->
     Redis `edu:heatmap:<content>:<date>` (absolute values per window, so replay is safe; TTL 48 h).
   * BR8: per (course, learner, day) engagement score via `EngagementPolicy` weights ->
     Redis `edu:engagement:<course>:<date>`.
   Fills `video_heatmap_job.py`, `engagement_trend_job.py`; `flink_env.py` stays a stub.
4. **Batch marts.** Unchanged SQL; add a `lakehouse-batch` compose service that runs
   `edu warehouse run` on an interval (Airflow DAGs remain the production schedule).
5. **Content sync (BR8).** Adapters: `s3_document_store.py` (MinIO versioned objects),
   `opensearch_index.py` (`VectorIndex` + `SearchIndexer`, BM25 + kNN on chunks),
   Redis `CacheInvalidator`, PostgreSQL-backed `ContentRepository`.
   `services/content_sync/main.py`: consume `cdc.lms.public.course_content` ->
   `PublishContentVersion` sync steps -> emit `content.updated.v1` / `content.indexed.v1`
   (already landed into `gold.fct_content_sync`). `content_chunking_embedding_job.py`:
   Spark backfill/reindex of the whole corpus. Embeddings use a deterministic local
   hashing embedder behind a port (no model download/GPU); documented as a limitation.
6. **Serving.** `contexts/analytics/infrastructure/trino_mart_reader.py` (new `trino`
   client dependency) + Redis overlay reader. New scoped routes reusing the BR4/BR5 bearer
   principal, with a new `admin` role scoped to organisations:
   * `GET /api/admin/organisations/{org}/progress` (k=5 suppression comes from the mart; API never un-suppresses)
   * `GET /api/instructor/videos/{content}/heatmap?version=` (mart + optional live overlay)
   * `GET /api/instructor/courses/{course}/engagement` (weekly trend + live today)
   * `POST /api/instructor/content/{content}` writes PostgreSQL + MinIO (CDC drives sync);
     `GET .../content/{content}` sync status; `GET /api/instructor/courses/{course}/search?q=`
   Each response carries `as_of` / freshness so the UI shows mart age.
7. **UI.** Admin and Instructor views switch to the persistent APIs behind the existing
   `AnalyticsAccess` token flow; heatmap gains version selector + live overlay toggle;
   content panel shows async sync status and a search box.
8. **Compose profile `br678`:** `opensearch`, `br678-init` (connector, topics, seed,
   warehouse bootstrap, OpenSearch index template), `lakehouse-streaming`,
   `telemetry-live`, `content-sync`, `lakehouse-batch`.

## Processing dependency map

`telemetry producer -> Kafka raw -> Spark normalise -> learning_events -> Spark windows -> Redis (live)`
`raw/CDC -> bronze -> silver -> gold -> mart (Spark batch) -> Trino -> API -> Admin/Instructor views`
`course_content row + MinIO object -> WAL -> Debezium -> content-sync -> Redis invalidate, chunk, OpenSearch -> content.* events -> fct_content_sync`

## Validation gates

* Unit: SQL/Python parity for each mart against the existing use cases
  (`BuildOrgProgressReport`, `BuildVideoHeatmap`, `ComputeEngagementTrend`) on shared fixtures;
  k-anonymity never leaks a rate below k; schema 1.0 -> 1.1 migration; no raw learner id
  after normalisation; chunking idempotence; architecture guardrails still pass.
* Integration (testcontainers / compose): Trino reader, OpenSearch adapter, Redis overlay,
  authorization (admin sees only own orgs, instructor only own courses).
* E2E: telemetry -> mart -> API; late mobile events recompute the right partition;
  content edit in PostgreSQL -> CDC -> cache invalidated -> search returns new text, old
  version gone; replay/restart of the streaming checkpoint gives identical overlay values.
* Browser (Playwright) for Admin and Instructor panels.
* Benchmarks (CSV under `evidence/br678/`): event-to-overlay latency, mart build time vs
  event volume, content-change-to-searchable latency.
* `docs/BR6_BR7_BR8_IMPLEMENTATION.md` with runbook, measured results and limitations.

## Risks

Laptop resources: Trino (2 GB) + OpenSearch (~1 GB) + two Spark drivers + emulated Hive
Metastore on Apple silicon. Profile keeps each Spark app at `local[2]`; OpenSearch heap 512 MB.
The demo mode stays untouched for BRs and machines that do not run the profile.
