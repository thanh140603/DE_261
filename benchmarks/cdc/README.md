# Debezium vs polling (negative-control benchmark)

This compares the chosen CDC path with a simpler `updated_at` polling baseline on
the same PostgreSQL table. It is not an "upgrade" benchmark: polling is a common
small-scale solution that loses correctness at Big Data scale.

## Result

Source: 100,000 rows, indexed `updated_at`, 100 UPDATE + 10 hard DELETE.

| Metric | Debezium | Polling |
|---|---:|---:|
| Events | 110 | 100 |
| Updates | 100 | 100 |
| Hard deletes | **10** | **0** |
| Latency p50 | 28.9 ms | 446.6 ms |
| Latency p95 | 512 ms | 447.6 ms |
| Polling query p50 | — | 14.3 ms |
| Query source table (SELECT/scan) | 0 | 16 |
| PostgreSQL tuples returned by table queries | 0 | 4,337 |

Raw result: [results/cdc_100k_indexed.json](results/cdc_100k_indexed.json).

The key failure is correctness: polling cannot see a hard-deleted row. Debezium
also keeps offsets/LSN and transaction ordering; polling only has a watermark.

The `0` query count is measured **after the initial snapshot**; Debezium did read
100,000 rows during snapshot. It means no table SELECT/scan in the measured window,
not "zero SQL" at all. The `tup_returned` value counts index/heap tuples touched by
polling queries, not logical events.

## Run

Prerequisites: Kafka, Debezium Connect, PostgreSQL running.

```bash
# 1. Build the source table from the generated facts CSV
.venv/bin/python -m benchmarks.cdc.setup_source \
  benchmarks/cdc/data/org-facts-1m.csv --rows 100000

# 2. Register the connector (once)
curl -sS -X DELETE http://localhost:8083/connectors/bench-cdc >/dev/null 2>&1 || true
curl -sS -X POST -H 'Content-Type: application/json' \
  --data @benchmarks/cdc/connector.json http://localhost:8083/connectors

# 3. Wait until the snapshot reaches 100,000 offsets
docker exec de261-kafka kafka-run-class kafka.tools.GetOffsetShell \
  --broker-list localhost:9092 --topic bench.bench.cdc_source

# 4. Run
.venv/bin/python -m benchmarks.cdc.run_benchmark \
  --duration 8 --updates 100 --deletes 10 \
  --out benchmarks/cdc/results/cdc_100k_indexed.json
```

Generate the CSV if needed:

```bash
.venv/bin/python benchmarks/cdc/generate_facts.py \
  --size-gb 5 --output benchmarks/cdc/data/org-facts-5gb.csv
head -n 1000001 benchmarks/cdc/data/org-facts-5gb.csv \
  > benchmarks/cdc/data/org-facts-1m.csv
```

To rerun from scratch, delete the connector and drop the replication slot before
recreating the table, otherwise the connector keeps its old snapshot position.
