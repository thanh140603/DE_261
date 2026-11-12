# Alternative-stack benchmarks

Local-only harness for comparing the selected stack with scale-oriented alternatives.
It is **not** part of the BR1–BR8 serving path.

## Status

| Pair | Current | Alternative | Status |
|---|---|---|---|
| B. OLAP | PostgreSQL | ClickHouse (StarRocks fallback) | measured 1M/5M/10M |
| C. Feature store | Redis (4 GiB) | Memcached (4 GiB) | measured 1M/5M |
| A. Streaming | Spark Structured Streaming | Flink 1.19 SQL | measured 100k filter |
| D. Data layout | Partition by date | Z-order / liquid clustering | measured 1M/5M/10M |

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
  --profile bench-kv up -d bench-redis bench-memcached
.venv/bin/python -m benchmarks.alternatives.feature_store.load_redis \
  data/features-1m.jsonl --port 6381
.venv/bin/python -m benchmarks.alternatives.feature_store.load_memcached data/features-1m.jsonl
.venv/bin/python -m benchmarks.alternatives.feature_store.query_memcached \
  --rows 1000000 --label 1m
```

`bench-redis-full` and `bench-memcached` use 4 GiB; both hold the complete
working set. `bench-redis` (512 MiB) remains only for the separate memory
pressure experiment. PostgreSQL is a disk reference, not the speed comparison.

## Data layout

```bash
docker run --rm --memory=6g --network de261_default \
  -v "$PWD/benchmarks/alternatives/data:/data:ro" \
  -v "$PWD/benchmarks/alternatives/layout:/script:ro" \
  -v "$PWD/benchmarks/alternatives/results/layout:/results" \
  de261/spark:local spark-submit --driver-memory 4g \
  /script/run_layout.py --csv /data/org-facts-5m.csv --rows 5000000 \
  --out /results/layout_5m.json
```

## Streaming

Measured on a 100k-event filter: see `results/streaming/summary.json`.
The Flink Kafka SQL connector JAR is not committed; download it before rerunning
the Flink side.
