# BR4 / BR5 implementation plan

The existing application uses FastAPI, React 18/TypeScript and an in-memory demo.
PostgreSQL 16, Debezium 2.6, Kafka and Spark 3.5.1 already run in Compose; the
BR4 batch and BR5 streaming entrypoints are stubs. No authentication exists.
Existing learner, notification, recommendation, content and video features stay intact.

## Dependencies and files

1. `infra/postgres/br45.sql`: additive, versioned OLTP tables in `br45`, and
   durable raw/clean/mart/alert/outbox tables in `analytics`.
2. `src/edu_platform/br45/`: contracts, PostgreSQL storage, assessment aggregation,
   risk policy, CDC landing/outbox worker, Spark window job, scoped API, fixtures,
   CLI and benchmarks. Reuse PostgreSQL as analytical serving storage, Kafka as
   transport and Spark as the processing engine; avoid another database/engine.
3. `infra/debezium/br45-connector.json`, `infra/br45/`, Compose profile `br45`:
   independent connector, CDC worker, Spark driver and persistent checkpoints.
4. FastAPI mounts scoped BR4/5 routes; Instructor and Advisor views consume
   persisted analytical APIs. Other BR views keep their existing demo adapters.
5. Deterministic unit, PostgreSQL/API integration, real CDC/Spark end-to-end and
   browser tests; measured CSV benchmark evidence and implementation runbook.

## Processing dependency map

`br45 OLTP -> PostgreSQL WAL -> Debezium -> Kafka -> transactional raw/clean landing`

* BR4: clean assessment revisions -> validated attempts -> SQL pass-rate marts
  -> explainable anomalies -> instructor APIs -> existing Instructor view.
* BR5: clean activity mutations -> transactional signed-event outbox -> Kafka
  -> Spark event-time hopping windows -> window mart -> explainable risk/alerts
  -> advisor APIs -> existing Advisor view.

The signed-event stream retracts old activity on updates/deletes. Stable event
identities, raw Kafka offsets, database transactions, Spark checkpoints and
upserted window outputs protect replay. Clock events allow inactivity to advance
without waiting for a learner event. Storage timestamps are UTC.

## Validation gates

Run domain/SQL parity tests, real database and authorization tests, the actual
PostgreSQL-to-Kafka-to-Spark workflow, restart/replay/correction cases, frontend
build and browser checks. Benchmark multiple sizes and compare SQL/Python BR4
and streaming/batch BR5 semantics. Record executed results and limitations;
never substitute simulation for CDC evidence.
