# ADR 0011: Spark owns every Delta write; Flink publishes to Kafka and Redis

Status: accepted - 2026-10-18 (refines ADR 0004 and ADR 0005)

## Context
ADR 0004 assigns stateful low-latency streaming to Flink and batch to Spark; several Flink job
stubs planned to write silver/gold Delta tables directly. As of Delta 4.2 the legacy Flink
connector is deprecated and its Kernel-based replacement is experimental and targets Flink 2.x;
the platform runs Flink 1.19. Multiple engines writing the same Delta table also invites
commit conflicts and duplicated idempotency logic.

## Decision
- **Flink** keeps the low-latency, stateful work (normalisation fast path, session features,
  live heatmap/engagement) and writes **only to Kafka and Redis**. BR5 risk windows run on
  Spark Structured Streaming with PostgreSQL state (ADR 0009); that runtime does not write
  Delta either, so the rule below holds for every engine. Kafka / Redis outputs:
  `telemetry.learning_events.v1`, `telemetry.events.dlq.v1`, `risk.dropout_alert.v1`,
  `risk.learner_score.v1` (new), `features.session.v1`, Redis keys.
- **Spark Structured Streaming** (`edu stream lakehouse-landing`) is the single writer of the
  lakehouse: Kafka -> bronze (append, checkpointed, exactly-once) and bronze -> silver
  (Delta stream + foreachBatch running the same SQL/Python models as the batch path).
- **Spark batch** (`edu warehouse run`, Airflow) builds gold, marts and features.
- The telemetry normalisation use case runs in both engines (ADR 0002): Flink for the
  real-time branch, Spark for the lakehouse; identical code, identical results.

## Consequences
- One writer per Delta table; idempotency (MERGE keys, REPLACE WHERE windows) lives in one place.
- Lakehouse freshness = landing trigger (1 min) + silver trigger (5 min); real-time needs
  (< 1 min) are served from Redis by Flink, as before.
- Revisit when the platform moves to Flink 2.x and the Kernel connector is GA.

Sources: Delta 4.2 release notes (delta.io/blog/2026-04-17-delta-4-2-released/),
delta-io/delta flink/README.
