# ADR 0003: Kafka and Debezium for ingestion and CDC

Status: accepted - 2026-09-29

## Context
Telemetry is high-velocity, late and out of order; OLTP changes must stream row-level in commit order without loading production.

## Decision
Kafka is both ingestion buffer and event bus (topic catalogue in infra/kafka/topics.yaml). Debezium (pgoutput plugin, replication slot) captures Postgres tables into cdc.lms.* with ExtractNewRecordState and lsn/op metadata. Keys: learner_id for telemetry, primary key for CDC - preserves per-entity ordering.

## Consequences
Replication slot must be monitored (WAL growth if a consumer stalls). Schema Registry + versioned contracts required for safe evolution.
