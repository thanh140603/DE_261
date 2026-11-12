# Alternative-stack benchmarks

Local-only harness for comparing the selected stack with scale-oriented alternatives.
It is **not** part of the BR1–BR8 serving path.

## Status

| Pair | Current | Alternative | Status |
|---|---|---|---|
| B. OLAP | PostgreSQL | ClickHouse | measured 1M/5M/10M |
| C. Data layout | Partition by date | Z-order / liquid clustering | measured 1M/5M/10M |
| A. Streaming | Spark Structured Streaming | Flink 1.19 SQL | measured 100k filter |

See [results/summary.md](results/summary.md) for numbers and caveats.
StarRocks/Flink numbers must not be inferred from the fallbacks.

## Data

Generated 5 GiB files live in `data/` (gitignored):

```bash
.venv/bin/python benchmarks/alternatives/streaming/generate_events.py --size-gb 5
.venv/bin/python benchmarks/alternatives/olap/generate_facts.py --size-gb 5
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
