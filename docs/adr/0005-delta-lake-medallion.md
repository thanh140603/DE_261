# ADR 0005: Delta Lake medallion lakehouse on object storage

Status: accepted - 2026-09-29

## Context
Need ACID upserts (dedup, CDC apply), time travel for reproducible features, and PII boundaries between raw and analytical data.

## Decision
Bronze (raw, immutable) -> silver (normalised, pseudonymised, deduped, CDF enabled) -> gold (marts, feature groups). Delta chosen over Iceberg for Databricks compatibility and Flink/Spark connector maturity; Iceberg remains a supported swap behind platform.batch.delta_tables.

## Consequences
Requires OPTIMIZE/VACUUM maintenance job; small-file risk from streaming writers mitigated by compaction.
