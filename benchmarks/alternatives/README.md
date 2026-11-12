# Alternative-stack benchmarks

Local-only harness for comparing the selected stack with scale-oriented alternatives.
It is **not** part of the BR1–BR8 serving path.

## Status

| Pair | Current | Alternative | Status |
|---|---|---|---|
| B. OLAP | PostgreSQL | ClickHouse (StarRocks fallback) | measured 1M/5M/10M |
| C. Feature store | Redis (4 GiB, full data) | PostgreSQL JSONB | measured 1M/5M |
| A. Streaming | Spark Structured Streaming | Flink 1.19 SQL | measured 100k filter |

See [results/summary.md](results/summary.md) for numbers and caveats.
StarRocks/Flink numbers must not be inferred from the fallbacks.

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
.venv/bin/python -m benchmarks.alternatives.feature_store.load_redis \
  data/features-1m.jsonl --port 6381
.venv/bin/python -m benchmarks.alternatives.feature_store.load_postgres data/features-1m.jsonl
.venv/bin/python -m benchmarks.alternatives.feature_store.workload_fair \
  --rows 1000000 --label 1m
```

`bench-redis-full` uses 4 GiB and must hold the complete working set for the
fair comparison. `bench-redis` (512 MiB) remains only for the separate memory
pressure experiment.

## Streaming

Measured on a 100k-event filter: see `results/streaming/summary.json`.
The Flink Kafka SQL connector JAR is not committed; download it before rerunning
the Flink side.
