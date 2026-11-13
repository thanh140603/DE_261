# What was implemented for BR6, BR7 and BR8

Implemented and evaluated on 2 November 2026 on the local Docker stack (Colima VM, 6 CPU,
10 GB). All data is synthetic. Plan and phase log: [BR6_BR7_BR8_PLAN.md](BR6_BR7_BR8_PLAN.md).
Decisions: [ADR 0013](adr/0013-br8-content-sync-cdc-opensearch.md) (content sync),
[ADR 0014](adr/0014-spark-streaming-telemetry-live-overlays.md) (live overlays).

## 1. What changed

| Area | Before | Delivered |
|---|---|---|
| BR6 serving | Admin view computed from the in-process demo | `mart.org_progress` read through Trino; admin tokens scoped to organisations; k = 5 suppression enforced by the mart and never relaxed by the API |
| BR7 serving | Demo heatmap from in-memory events | `mart.video_heatmap` per **video version** through Trino + today's streamed overlay |
| BR8 engagement | Demo trend from in-memory events | `mart.engagement_trend` through Trino + today's streamed scores |
| BR8 content sync | In-process steps inside the publish request | Publish writes a versioned object + the LMS row; Debezium CDC drives a `content-sync` service: Redis cache invalidation, chunking + embeddings into OpenSearch, search refresh, sync events |
| Telemetry fast path | Flink stub (`NotImplementedError`) | Spark Structured Streaming normalisation -> `telemetry.learning_events.v1` / DLQ |
| Live overlays | Flink stubs | Spark event-time aggregations -> Redis (absolute values) |
| Corpus backfill | Spark stub | `edu batch content-reindex`: same use case per item slice, `silver.content_chunks` |
| Evidence | none | Unit, Spark, real-service integration and browser tests; measured benchmarks (section 9) |

The BR4/BR5 runtime, the BR1-BR3 demo and the original demo endpoints are untouched.

## 2. Requirements traceability

| | BR6 Admin / B2B | BR7 Instructor | BR8 Instructor |
|---|---|---|---|
| PDF need | Medallion pipeline: schema versioning, PII removal, org report with min cohort | Play / pause / rewind density per video second | Cache invalidation + search refresh on content change; engagement windows, score, declining trend |
| Ingestion | Telemetry (Kafka) + LMS CDC (Debezium) -> bronze | Telemetry | LMS `course_content` CDC; telemetry |
| Processing | Spark silver (`NormalizeEvents`: migrate 1.0 -> 1.1, pseudonymise, drop PII) -> gold -> `mart.org_progress` | `gold.fct_video_second_activity` -> `mart.video_heatmap` (per version); live: Spark windows | `SyncContentChange` (content-sync); `mart.engagement_trend`; live: Spark windows |
| Storage / serving | Delta + Trino | Delta + Trino; Redis overlay | Redis cache, OpenSearch (BM25 + kNN), Delta + Trino, Redis overlay |
| API | `/admin/organisations/{org}/skill-progress` | `/instructor/courses/{c}/videos`, `/instructor/videos/{id}/interaction-heatmap` | `/instructor/courses/{c}/engagement-trend`, `/instructor/content/...`, `/instructor/courses/{c}/search` |
| UI | Admin | Instructor: heatmap (version, live toggle) | Instructor: engagement (live today), content sync + search |
| Evidence | k-anonymity gate, API scope tests, browser test | reader SQL on real Delta, live parity test, browser test | CDC end-to-end (real stack), real OpenSearch tests, browser tests |

## 3. Architecture

```text
 clients ─► telemetry.events.raw.v1 ─┬─► lakehouse-streaming ─► bronze ─► silver ─► gold ─► mart ─► Trino ─┐
                                     │      (Spark, ADR 0011)        (edu warehouse run, daily)            │
                                     └─► telemetry-live (Spark, ADR 0014)                                  │
                                           normalise ─► telemetry.learning_events.v1 / DLQ                 ├─► API ─► Admin /
                                           BR7 per-second counts ─┐                                        │          Instructor
                                           BR8 daily scores ──────┴─► Redis edu:live:* ───────────────────┤
 LMS PostgreSQL course_content ─► WAL ─► Debezium ─► Kafka ─► content-sync ─► Redis cache, OpenSearch ────┘
        ▲                                                         └─► content.updated / content.indexed ─► bronze ─► gold.fct_content_sync
        └── instructor publish (row lock) + MinIO corpus object (one immutable key per version)
```

Hexagonal layout is kept: ports in `contexts/*/application/ports.py`, adapters in
`contexts/*/infrastructure`, composition in `entrypoints`. The architecture guardrail test
passes for every new module.

## 4. Files and responsibilities

| File | Responsibility |
|---|---|
| `contexts/analytics/application/ports.py` | Mart read models, `AnalyticsMartReader`, live-overlay port |
| `contexts/analytics/infrastructure/trino_mart_reader.py` | ANSI SQL reads (Trino in production, Spark in tests) |
| `contexts/analytics/infrastructure/cached_mart_reader.py` | 60 s TTL cache (marts change daily; dashboards poll) |
| `contexts/analytics/infrastructure/redis_live_overlay.py` | Live overlay writer (stream) and reader (API) |
| `contexts/content/domain/sync_policy.py` | CDC-safe idempotency: apply newer, skip duplicate / stale |
| `contexts/content/domain/chunking.py` | Fixed: no longer drops short sections |
| `contexts/content/application/sync_content_change.py` | Fetch, invalidate, chunk + embed, prune, index, warm, events |
| `contexts/content/application/submit_content_version.py` | Write side: new object + LMS row under a row lock |
| `contexts/content/infrastructure/*` | S3 (versioned), Redis cache, OpenSearch, hashing embedder, PostgreSQL catalog, Debezium parser |
| `contexts/telemetry/domain/events.py` | `ClockSkewPolicy` (future-dated events pinned to ingestion time) |
| `entrypoints/api/routers/lakehouse.py`, `content.py` | Scoped APIs (shared bearer tokens + `admin` role) |
| `entrypoints/services/content_sync/` | Service, composition root, `edu content` admin commands |
| `entrypoints/streaming/telemetry_*`, `video_heatmap_job.py`, `engagement_trend_job.py` | Live app and its three queries |
| `entrypoints/batch/content_chunking_embedding_job.py` | Spark corpus reindex with per-item failure isolation |
| `entrypoints/batch/br678_benchmark.py` | `edu benchmark marts / serving / content / live / environment` |
| `warehouse/quality/mart_*` | Warn gates for unresolved dimensions in BR6/BR7 marts |
| `apps/web/src/views/AdminView.tsx`, `InstructorView.tsx`, `analytics.ts` | Dashboards on the persistent APIs |
| `docker-compose.yml` (profile `br678`), `infra/trino/*.config`, `Dockerfile` | Runtime |

## 5. Semantics that matter

- **k-anonymity (BR6).** A cohort below `MinCohortPolicy.k = 5` is published with its size
  only. The reader nulls the rates of a suppressed row even if a faulty mart carried one, and
  the error-level gate `mart_org_progress_k_anonymity` fails the build otherwise.
- **Versions (BR7).** Events are attributed to the content version valid at event time
  (`gold.dim_content`, SCD2), so a re-recorded video has one heatmap per version; the API
  defaults to the newest. Positions past the end clamp to the last second (mart and live).
- **Engagement (BR8).** Weekly windows, declining = score down ≥ 30 % in each of the last
  two windows (`EngagementPolicy`). Live "today so far" uses the same verb weights
  (`verb_weights`), so it equals tomorrow's warehouse value for that day.
- **Content sync idempotency.** Decided against the indexed version, not arrival order;
  replays and old snapshots are no-ops; search returns only each item's current version.
- **`in_sync`.** Read at search visibility, so it is true only when search can see the version.
- **Live overlays.** Watermark 5 min; later events reach only the marts. Overlays are written
  as absolute values, so replays never double count. Live data covers only days after the
  mart snapshot and only the newest video version; Redis outages degrade to mart-only.

## 6. APIs, auth and UI

See the *Lakehouse analytics* and *Content sync* sections for API contracts.
[API documentation](api.md)

Provision Admin and Instructor accounts with the assigned organisations or courses.
The Instructor session works across the BR4, BR7 and BR8 panels. API scripts can
use tokens from `EDU_BR45_AUTH`. [Account setup](STAFF_AUTH.md)

## 7. Defects found and fixed while validating

| Defect | Impact | Fix |
|---|---|---|
| Chunker dropped every section < 64 words after the first | ~2/3 of each transcript never searchable | Merge into the previous chunk of the same section or keep alone |
| Heatmap default picked the oldest version when a re-cut was retitled | Wrong video shown by default | Order versions by id/version, not title |
| `/document` returned cache hits before the scope check | Cached document readable outside scope | Scope first, then cache; regression test |
| `in_sync` read in real time | "Synced" up to 1 s before searchable | Read at search visibility |
| `refresh=wait_for` on every sync | ~2 s per sync | `refresh=True` (rare writes): 25-70 ms |
| Demo image lacked the LMS connector file | `content-init` failed | Copied in `Dockerfile` |
| One missing object aborted the whole Spark reindex | No item reindexed | Per-item isolation, exit 1 listing failures |
| Future-dated client clocks advanced the watermark | Everyone's on-time live events silently dropped | `ClockSkewPolicy` in the domain |
| Trino heap = 80 % of a 2 GB container; uncached dashboard polling | Trino OOM-killed | 1.2 GB heap, restart policy, `CachedMartReader` |
| `pull_policy: build` on MinIO | Every `compose run` recreated MinIO | Removed |
| Live normalise ran three Spark jobs per batch | 3.4 s batches | One Kafka write routed by `topic` column: 2.7 s |
| Playwright JSON reporter path | A BR6-BR8 run would overwrite BR4/BR5 evidence | `EVIDENCE=br678` selects the folder |

## 8. Executed correctness evidence

- **Unit (346):** API scopes and errors with fakes, sync policy, use cases, Debezium parsing,
  S3 (moto, versioned), Redis (fakeredis), OpenSearch adapter, live overlay, cache, producer.
- **Spark (9, `-m spark`):** mart reader SQL on Delta tables built from `warehouse/ddl`;
  reindex job on Delta with a moto S3 server; live streaming parity on real Kafka + Redis.
- **Real services (`-m integration`):** OpenSearch 2.17 (analyzer, HNSW, kNN filter, current
  version only), PostgreSQL catalog (5 concurrent publishers -> versions 2-6, rollback),
  streaming parity: overlays equal `NormalizeEvents` + `EngagementPolicy` on the same events,
  including client re-sends and a full replay from fresh checkpoints.
- **Real stack:** warehouse built with the README commands, all 10 quality gates 0; Debezium
  snapshot of 8 documents synced, 8 + 8 content events; CDC delete removed vectors + search
  entry; reindex job wrote 20 chunks and reported 19 items without objects (section 11).
- **Fresh one-command bring-up:** after `down -v`, `docker compose --profile br678 up -d
  --build` took ~4 min; `br678-init` built 43 models, `content-init` uploaded 8 transcripts,
  created the indices and registered Debezium, `content-sync` synced all 8; the browser suite
  then passed ([results](evidence/br678/browser-results.json)).
- **Browser (4, `apps/web/tests/br678.spec.ts`):** Admin k-anonymity and scope, per-version
  heatmap and engagement, publish -> searchable through the real CDC path, live overlays.
  Screenshot: [instructor live](evidence/br678/instructor-live.png).

## 9. Measured performance

Environment: [environment.json](evidence/br678/environment.json). Local observations with
the whole stack running on one laptop VM, not capacity guarantees. Raw CSVs keep every sample.

### Serving ([serving_latency.csv](evidence/br678/serving_latency.csv), 30 requests each)

| | Uncached warehouse reads (Trino) median / p90 / max | API, mart cache warm median / p90 / max |
|---|---:|---:|
| BR6 org progress | 63.0 / 92.4 / 219.3 ms | 1.4 / 1.8 / 6.0 ms |
| BR7 heatmap (390 s video) | 92.1 / 136.0 / 159.3 ms | 2.5 / 2.8 / 4.9 ms |
| BR8 engagement (38 learners) | 41.6 / 58.6 / 204.9 ms | 1.6 / 2.0 / 104.4 ms |

### BR8 content sync ([content_sync_latency.csv](evidence/br678/content_sync_latency.csv), 20 publishes)

Publish (API accepted in 16.9 ms median) -> PostgreSQL WAL -> Debezium -> Kafka ->
content-sync -> searchable: **median 535 ms, p90 992 ms, max 1,024 ms**. The sync itself
takes 25-70 ms; the rest is capture and consumer polling.

### Live overlays ([live_overlay.csv](evidence/br678/live_overlay.csv), 3 bursts per size)

| Sessions per burst | Raw events (mean) | Event -> visible in API, mean (min-max) | Exact |
|---:|---:|---:|---|
| 25 | 234 | 7.27 s (7.19-7.35) | yes |
| 100 | 888 | 7.23 s (6.95-7.38) | yes |
| 400 | 3,622 | 7.12 s (5.69-8.03) | yes |

Latency is flat across a 15x load range: it is dominated by the fixed per-micro-batch cost
(normalise ~2.7 s, 1 s triggers), not by volume. "Exact" = the overlay held exactly the
expected on-time interactions of the burst for the busiest video.

### Warehouse build ([mart_build.csv](evidence/br678/mart_build.csv))

| Days | Silver events | Total build, mean (runs) | Silver | Gold | Marts | org_progress | video_heatmap | engagement_trend |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 35 | 10,761 | 143.7 s (123.196, 164.25) | 32.6 s | 54.9 s | 11.6 s | 2.42 s | 4.67 s | 1.95 s |
| 70 | 20,486 | 128.6 s (120.792, 136.398) | 36.1 s | 48.8 s | 6.3 s | 1.37 s | 1.94 s | 1.61 s |
| 140 | 40,221 | 135.8 s (134.825, 136.847) | 37.3 s | 51.1 s | 7.0 s | 1.48 s | 1.88 s | 1.86 s |

Each run is a fresh Spark process (`local[*]`, isolated in-memory catalog and local Delta
directory), 43 models plus quality gates, all succeeded. The build time is nearly flat over
a 4x volume range: at this scale it is dominated by fixed per-model cost (Spark jobs, Delta
commits, quality checks), and the BR6-BR8 marts themselves take 1-6 s. The spread between
repetitions (e.g. 123 vs 164 s at 35 days) is noise from the shared laptop VM with the rest of
the stack running. Running six builds in **one** driver failed on the fourth with a driver
out-of-memory error (broadcast join): the job's default 1 GB driver is enough per run, but
not for repeated runs in one process; set `spark.driver.memory` before reusing a session or
scaling the data well beyond this.

## 10. Runbook

```bash
# everything, incl. warehouse (br678-init), content sync and live overlays
docker compose --profile br678 up -d --build
docker compose --profile br678 logs -f br678-init content-init      # first start: a few minutes

# Sign in to Admin and Instructor at :8000 with the provisioned accounts.
docker compose exec demo edu telemetry simulate --sessions 50         # live overlay input

# checks
uv run pytest tests/unit                                              # 346
uv run pytest -m spark tests/integration                              # needs a JDK
uv run pytest -m integration tests/integration/test_opensearch_real.py \
  tests/integration/test_postgres_content_catalog.py                  # stack running
cd apps/web && EVIDENCE=br678 BR45_BASE_URL=http://localhost:8000 npx playwright test tests/br678.spec.ts

# benchmarks (write docs/evidence/br678)
uv run edu benchmark serving --out docs/evidence/br678/serving_latency.csv
uv run edu benchmark content --out docs/evidence/br678/content_sync_latency.csv
uv run edu benchmark live --out docs/evidence/br678/live_overlay.csv
docker compose run --rm -v "$PWD/docs/evidence/br678:/out" spark-jobs \
  edu benchmark marts --out /out/mart_build.csv
```

Stop without losing data: `docker compose --profile br678 stop`. `down -v` deletes all volumes.

## 11. Limits and next steps

- **Seed mismatch (owner needed).** `demo/seed.py` (bronze seed) declares about 18
  courses/videos that `infra/postgres/init.sql` does not, so the lakehouse references content
  with no LMS row or transcript; `content-reindex` reports them as failures.
- **Embeddings are lexical** (hashing embedder). A sentence-embedding model is a new adapter
  plus a forced reindex; vectors already carry their model name.
- **Live overlay latency ~7 s** (Spark micro-batches in `local[2]`). Sub-second would need
  Flink (the PDF's choice) or a non-JVM consumer; ADR 0014 records the trade-off.
- **Live events carry no content version**: on a re-cut day the overlay mixes both versions.
- **Single-node services** (Trino, OpenSearch, Kafka) with local-only security settings
  (OpenSearch security plugin disabled); production needs TLS, auth and replication.
- **Warehouse cadence**: marts are daily; `br678-init` builds once, Airflow DAGs
  (`orchestration/airflow`) remain the production schedule and are not in compose.
