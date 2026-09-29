# ADR 0004: Apache Flink for streaming, Apache Spark for batch

Status: accepted - 2026-09-29

## Context
BR2/BR5/BR7/BR8 need stateful, event-time windows with low latency; BR2 batch features, BR4/BR6 marts and corpus embedding are throughput-bound.

## Decision
Flink for stateful streaming (RocksDB state, exactly-once checkpoints, event-time watermarks). Spark + Delta for batch and backfills. Spark Structured Streaming was rejected for the risk job because of micro-batch latency and weaker per-key timers; using only Flink was rejected because Spark's batch ecosystem (Delta, MLlib, embedding UDF parallelism) is stronger.

## Consequences
Two engines to operate; mitigated by engine-agnostic use cases and shared platform factories.
