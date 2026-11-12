# Alternative-stack benchmarks

Local-only harness for comparing the selected stack with scale-oriented alternatives.
It is **not** part of the BR1–BR8 serving path.

## Status

| Pair | Current | Alternative | Status |
|---|---|---|---|
| B. OLAP | PostgreSQL | ClickHouse (StarRocks fallback) | measured 1M/5M/10M |
| C. Feature store | Redis (512 MiB cap) | PostgreSQL disk store (ScyllaDB fallback) | measured 1M/5M |
| A. Streaming | Spark Structured Streaming | Flink | not completed on this host |

See [results/summary.md](results/summary.md) for numbers and caveats.
StarRocks/ScyllaDB/Flink numbers must not be inferred from the fallbacks.

## Data

Generated 5 GiB files live in `data/` (gitignored):

```bash
.venv/bin/python -m benchmarks.alternatives.feature_store.generate_features --size-gb 5
```

Subsets used by the benchmarks are deterministic prefixes (`1m`, `5m`, `10m`).

## OLAP

```bash
docker compose -f docker-compose.yml -f docker-compose.bench.yml \
  --profile bench-olap up -d bench-clickhouse
.venv/bin/python -m benchmarks.alternatives.olap.load_postgres data/org-facts-1m.csv
.venv/bin/python -m benchmarks.alternatives.olap.load_clickhouse data/org-facts-1m.csv
.venv/bin/python -m benchmarks.alternatives.olap.query_olap --engine both --label 1m
```

## Feature store

```bash
docker compose -f docker-compose.yml -f docker-compose.bench.yml \
  --profile bench-kv up -d bench-redis
.venv/bin/python -m benchmarks.alternatives.feature_store.load_redis data/features-1m.jsonl
.venv/bin/python -m benchmarks.alternatives.feature_store.load_postgres data/features-1m.jsonl
.venv/bin/python -m benchmarks.alternatives.feature_store.load_scylla data/features-1m.jsonl
.venv/bin/python -m benchmarks.alternatives.feature_store.workload --rows 1000000 --label 1m
.venv/bin/python -m benchmarks.alternatives.feature_store.query_scylla --rows 1000000 --label 1m
```

ScyllaDB needs a larger cgroup than the default 1 GiB image reservation:

```bash
docker compose -f docker-compose.yml -f docker-compose.bench.yml \
  --profile bench-kv up -d bench-scylla
```

## Streaming

Not run. A Flink Kafka SQL connector JAR is required and is not committed;
see `docs/ALTERNATIVE_STACK_BENCHMARK_PLAN.md` for the follow-up checklist.
