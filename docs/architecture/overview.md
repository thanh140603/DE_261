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

| Layer | Tables | Written by | Notes |
|-------|--------|-----------|-------|
| bronze | `telemetry_raw`, `telemetry_dlq`, `cdc_*` | IngestRawEvents, Debezium | immutable, raw PII, short retention, restricted ACL |
| silver | `learning_events`, `enrollments`, `lesson_progress`, `submissions`, `grades`, `content_items`, `content_chunks` | NormalizeEvents, CDC apply | pseudonymised, schema-current, deduped, Change Data Feed on |
| gold | `assessment_item_stats`, `org_progress_report`, `video_heatmap`, `engagement_trend`, `features_*` | analytics, recommendation | k-anonymity enforced on org reports |

## Streaming semantics

- Event time everywhere; watermark bounded out-of-orderness 5 min (telemetry), 10 s (CDC).
- Late data past the watermark is still persisted and flagged; the batch
  backfill (`bronze_to_silver_job`) is the authoritative recompute.
- Exactly-once: Flink checkpoints + Kafka transactions; idempotent Delta MERGE on `event_id`.
- CDC ordering by `source.lsn` per key; Debezium reads a replication slot so
  production query load is untouched.

## Cross-cutting

- PII: raw identifiers stop at bronze; keyed-hash `Pseudonymizer` applied at silver (ADR 0007).
- Schema versioning: `schema_version` in payload, chained migrations to current, contracts in `/schemas`.
- Observability (TODO): consumer lag, checkpoint duration, DLQ rate, freshness SLA per feature group.
