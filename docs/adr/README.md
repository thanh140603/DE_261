# Architecture Decision Records

Format: [MADR](https://adr.github.io/madr/) light. One file per decision, never
edited after acceptance - supersede with a new ADR instead.

| # | Decision | Status |
|---|----------|--------|
| 0001 | Record architecture decisions | accepted |
| 0002 | Python monorepo, DDD bounded contexts, hexagonal layers | accepted |
| 0003 | Kafka + Debezium for ingestion and CDC | accepted |
| 0004 | Flink for streaming, Spark for batch | accepted |
| 0005 | Delta Lake medallion lakehouse on object storage | accepted |
| 0006 | Redis as low-latency serving layer | accepted |
| 0007 | PII pseudonymisation at the silver boundary | accepted |
| 0008 | In-process demo runtime behind the same ports | accepted |
| 0009 | Trino + Hive Metastore as the SQL warehouse over Delta | accepted |
| 0010 | Spark owns every Delta write; Flink publishes to Kafka / Redis | accepted |
| 0011 | SeaweedFS replaces MinIO as the local S3 store | accepted |
| 0012 | Gold = Kimball star schema with deterministic surrogate keys | accepted |
