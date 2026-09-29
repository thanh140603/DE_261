# ADR 0008: In-process demo runtime behind the same ports

Status: accepted - 2026-09-29

## Context
The platform must be demonstrated end to end (web client + server) without
standing up Kafka, Debezium, Flink, Spark, Delta and Redis on a laptop, while
still showing the real pipeline behaviour: schema migration, PII
pseudonymisation, late/duplicate handling, sliding-window risk, feature
branches, rule-based notifications, content sync and the gold marts.

## Decision
Domain and application code is engine-agnostic (pure per-record functions and
use cases). `src/edu_platform/demo` provides in-memory adapters for every port
plus an in-process event bus that stands in for Kafka (topic log + synchronous
consumers). `entrypoints/api` (FastAPI) exposes the outcomes and the simulator
to the React client in `apps/web`. Production entrypoints (Flink/Spark jobs,
Kafka services) wire the same use cases to the real adapters (TODO stubs).

## Consequences
One code path for business rules in demo and production; the demo doubles as
an integration test of the domain. Demo-only shortcuts are explicit: batch
features and marts are recomputed on request instead of on a schedule, the
sandbox worker is a local subprocess/SQLite (not a security boundary), and
nothing is persisted across restarts.
