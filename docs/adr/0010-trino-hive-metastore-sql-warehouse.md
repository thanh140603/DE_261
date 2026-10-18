# ADR 0010: Trino + Hive Metastore as the SQL warehouse over the Delta lakehouse

Status: accepted - 2026-10-18

## Context
ADR 0005 made Delta Lake on object storage the analytical store ("Databricks / Delta Lake" in
the requirements). Delta is a table format, not a database: the "Databricks" half of that
choice - a shared catalog (Unity Catalog / Hive Metastore) and a SQL warehouse that serves
BI and the instructor / advisor / admin dashboards - was missing. Requirements for that role:
- query the gold / mart Delta tables in place (no second copy to keep consistent; ADR 0006
  already says everything must be rebuildable from the lakehouse);
- ANSI SQL, concurrent interactive queries, per-role access (PII boundary of ADR 0007,
  k-anonymous B2B access for BR6), time travel and Change Data Feed;
- runs on a laptop in docker compose and has a managed equivalent in the cloud.

## Decision
- **Catalog: Hive Metastore 3.1.3** (standalone service, Postgres-backed). Spark registers
  every table it creates; Trino (and later StarRocks / Flink) read the same catalog.
  3.1.x not 4.x: Spark 3.5's built-in Hive client fails against a Hive 4 metastore
  (`Invalid method name: 'get_table'`), Hive 4 needs Spark 4.1+.
- **SQL warehouse engine: Trino** (`delta_lake` connector, catalog `lakehouse`), read-only for
  every user: Spark is the single writer (ADR 0011). Access by schema in
  `infra/trino/rules.json`: `b2b_admin` -> `mart.org_progress` only, `app` -> gold + mart,
  `analyst` -> silver..features (pseudonymised), `pii_steward` -> bronze.
- **The warehouse itself is the gold layer** of the lakehouse, modelled as a Kimball star
  schema (ADR 0012), plus BR marts; see docs/architecture/data-warehouse.md.

## Alternatives considered
| Option | Why not (now) |
|---|---|
| Databricks SQL + Unity Catalog | Same role, managed; not runnable locally. Cloud target, no model changes needed. |
| StarRocks (Delta catalog + async MVs) | Faster dashboards (vectorised C++, MV acceleration) but needs HMS anyway, heavier locally. **Upgrade path**: attaches to the same HMS, no data movement. |
| ClickHouse (Kafka engine, ReplacingMergeTree) | Excellent for event analytics, but becomes a second store fed in parallel to Delta - contradicts ADR 0005/0006. |
| Apache Doris | Same trade-off as StarRocks. |
| Spark Thrift Server | Already have Spark, but poor interactive concurrency/latency for dashboards. |
| DuckDB (delta + uc extensions) | Embedded, single user; good for notebooks, not a shared serving endpoint. |
| Unity Catalog OSS as catalog | Databricks-native, but Spark 3.5 + Trino Delta support via UC OSS is less mature than HMS today; revisit with Spark 4. |

## Consequences
- One copy of the data, queryable by Spark (writes) and Trino (reads) through one catalog.
- Marts are small pre-aggregated tables, so Trino's per-query latency (sub-second to seconds)
  is adequate; sub-10 ms keyed reads stay in Redis (ADR 0006).
- HMS image is amd64-only (emulated on Apple silicon) and needs extra jars (Postgres driver,
  hadoop-aws) - built in infra/hive-metastore/Dockerfile.

Sources: Trino Delta Lake connector docs (trino.io/docs/current/connector/delta-lake.html);
StarRocks Delta Lake catalog docs (docs.starrocks.io); ClickHouse DeltaLake engine docs
(clickhouse.com/docs); Hive/Spark compatibility reports for HMS 4.
