# Architecture overview

## Context map

```
 clients (web/android/ios)      LMS PostgreSQL          Object storage        Sandbox workers
        |  JSON (xAPI-like)          |  WAL                  |  transcripts/pdf       |  exec logs
        v                            v                       v                        v
  telemetry.events.raw.v1     Debezium -> cdc.lms.*     content-sync svc      grading.sandbox_result.raw.v1
        |                            |                       |                        |
  +-----+------------+     +---------+---------+     +-------+--------+      +--------+---------+
  |  TELEMETRY (BR6) |     |    RISK (BR5)     |     | CONTENT (BR8)  |      |  GRADING (BR3)   |
  | bronze->silver   |     | Flink sliding win |     | chunk/embed    |      | queue+normalise  |
  | pseudonymise     |     | dropout alerts    |     | cache/search   |      | feedback         |
  +-----+------------+     +---------+---------+     +----------------+      +--------+---------+
        |  silver.learning_events    |  risk.dropout_alert.v1                        |  grading.submission_graded.v1
        v                            v                                               v
  +-----------------------+   +----------------------+                    +-----------------------+
  | RECOMMENDATION (BR2)  |   | NOTIFICATION (BR1)   |<-------------------| ANALYTICS (BR4/6/7/8) |
  | batch+stream features |   | rules, dedup, RL     |   (mart events)    | gold marts            |
  | Delta offline/Redis   |   | push/in-app/email    |                    +-----------------------+
  +-----------------------+   +----------------------+
```

All contexts are customer/supplier of the telemetry context's published
language (`silver.learning_events`). Notification is a downstream conformist of
every event topic. No shared database between contexts.

## Layers inside a context (hexagonal)

| Layer | Contains | May import |
|-------|----------|-----------|
| `domain/` | entities, value objects, aggregates, domain events, policies | `shared_kernel.domain` only |
| `application/` | use cases (one class, one `execute`), ports (`Protocol`) | domain, `shared_kernel.application` |
| `infrastructure/` | adapters: Kafka, Redis, Delta, S3, HTTP, YAML | anything, incl. `platform` |
| `entrypoints/` | composition roots for Flink / Spark / services | anything |

SOLID mapping: SRP = one use case per file. OCP = a new signal, rule or feature
is a new adapter or policy, not an edit to the use case. LSP = adapters are
substitutable via Protocols (in-memory fakes in tests). ISP = small ports per
capability (`DeadLetterSink`, `SilverSink`) instead of one fat storage port.
DIP = domain and application depend on ports, never on engines.

## Data flow (medallion)

Detailed design: [data-warehouse.md](data-warehouse.md) (model, marts, quality, security) and
[pipelines.md](pipelines.md) (pipeline catalogue, orchestration, late data, replay).

| Layer | Tables | Written by | Notes |
|-------|--------|-----------|-------|
| bronze | `telemetry_raw`, `telemetry_dlq`, `cdc_events`, `domain_events` | Spark landing stream (Kafka) | immutable, raw PII, retention 30/90 d, restricted ACL |
| silver | `learning_events`, LMS entities via CDC (`learners`, `enrollments`, `submissions`, ...), parsed domain events (`test_case_results`, `risk_scores`, ...), `content_chunks` | NormalizeEvents in Spark, CDC apply SQL | pseudonymised, schema-current, deduped, Change Data Feed on |
| gold | `dim_*` (9, conformed, SCD1/SCD2), `fct_*` (11) | warehouse models | Kimball star schema, deterministic surrogate keys (ADR 0012) |
| mart / features | `mart.assessment_item_stats`, `mart.org_progress`, `mart.video_heatmap`, `mart.engagement_trend`, `features.learner_longterm` | warehouse models | per-BR, domain thresholds, k-anonymity on org reports |

Served to SQL clients by Trino over the Hive Metastore catalog (ADR 0009); Spark is the only
writer of Delta tables, Flink publishes to Kafka / Redis (ADR 0010).

## Streaming semantics

- Event time everywhere; watermark bounded out-of-orderness 5 min (telemetry), 10 s (CDC).
- Late data past the watermark is still persisted and flagged; gold windows reach back to
  the oldest late event automatically (`late_data` in warehouse/models.yaml), and
  `edu warehouse run --start-date` is the authoritative recompute.
- Exactly-once: Flink checkpoints + Kafka transactions; Spark landing checkpoints + Delta
  transactional sink; idempotent Delta MERGE on business keys.
- CDC ordering by `source.lsn` per key; Debezium reads a replication slot so
  production query load is untouched.

## Cross-cutting

- PII: raw identifiers stop at bronze; keyed-hash `Pseudonymizer` applied at silver (ADR 0007).
- Schema versioning: `schema_version` in payload, chained migrations to current, contracts in `/schemas`.
- Data quality: gates per layer (`warehouse/quality`), results in `ops.dq_results`; every
  model build in `ops.pipeline_runs` (window, rows, Delta version).
- Observability (TODO): consumer lag, checkpoint duration, DLQ rate, freshness SLA per feature group.
