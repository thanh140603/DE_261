# ADR 0009: PostgreSQL marts and Spark Structured Streaming for BR4/BR5

Status: accepted — 2026-10-16

## Context

The application serves all BRs through an in-memory runtime. PostgreSQL,
Debezium, Kafka, Spark and Flink exist in Compose, but the BR4/BR5 adapters and
processing entrypoints are unfinished. The public LMS tables use UUIDs while
the application reference data uses string identifiers; questions, test
versions and meaningful activity events are absent from the public schema.

## Decision

Add versioned operational contracts in `br45` and analytical storage in
`analytics` inside the existing PostgreSQL instance. Preserve the public LMS
tables and existing connector. A separate Debezium connector captures actual
WAL changes. A transactional CDC landing worker creates raw, clean and signed
activity outbox records. Spark Structured Streaming calculates event-time
7-day hopping windows, with configurable slide and watermark, from Kafka.
PostgreSQL serves persistent assessment marts, risk states and alert history.

This decision supersedes ADR 0004's Flink-only choice **for BR5**. One executable
Spark driver with Python 3.11 requires less new infrastructure than completing
both engine adapters. A clock stream handles inactivity; measured local
CDC-to-alert latency of about 10 seconds is adequate for advisor intervention.
Other BRs and their planned engine choices are unchanged.

SQL aggregation is the BR4 baseline implementation. Python aggregation provides
an independently implemented correctness and performance comparison. BR5's
alternative is periodic batch aggregation with identical interval semantics.

## Consequences

The local path is executable, CPU-only and auditable. No ClickHouse, new broker,
paid service or unrelated frontend framework is introduced. BR4 refreshes the
affected materialization instead of maintaining fragile duplicate increments;
query caching uses the last accepted assessment revision. JSONB clean contracts
make CDC updates straightforward but cost more CPU than typed wide fact tables.

Spark's 5-second micro-batch trigger adds latency. The configured hourly slide
means risk is evaluated at the latest UTC hour boundary. Late activity within
the 21-day watermark is supported; older mutations require a controlled rebuild.
Outbox ids and Spark checkpoints protect replay, but checkpoints and analytical
window tables must be backed up/restored together. This is a single-machine
coursework deployment, not an availability or calibrated prediction claim.
