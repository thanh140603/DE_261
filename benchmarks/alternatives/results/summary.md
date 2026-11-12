# Alternative-stack benchmark — results

Environment: [environment.json](environment.json)
Host: AMD Ryzen 7 8745H, 16 vCPU, 7.4 GiB RAM, Ubuntu 26.04 WSL2, Docker 29.9.2.
All runs use the same generated 5 GiB datasets; subsets are deterministic prefixes.

## Pair B — PostgreSQL vs ClickHouse (OLAP)

Same `org-facts` CSV, same aggregation:
`GROUP BY org_id, course_id` with row count, distinct learners, average score,
average mastery and completed count. 3 measured runs after 1 warm-up.

| Rows | PostgreSQL load | ClickHouse load | PostgreSQL p50 | ClickHouse p50 | Speed-up |
|---:|---:|---:|---:|---:|---:|
| 1,000,000 | 10.80 s | 4.43 s | 6,289 ms | 84.96 ms | 74.0× |
| 5,000,000 | 53.44 s | 10.41 s | 33,829 ms | 369.81 ms | 91.5× |
| 10,000,000 | 96.24 s | 17.79 s | 69,898 ms | 664.76 ms | 105.1× |

Correctness: all 12 `(org_id, course_id)` groups match; integer counts match exactly,
float averages within 1e-9.

**Conclusion.** PostgreSQL remains the right transactional/serving store for small
marts, but its row-store aggregation degrades quickly with scale. ClickHouse
(MPP/columnar) is clearly better from 1M rows onward. StarRocks was not installed
on this host; ClickHouse is the documented fallback, not a StarRocks measurement.

## Pair C — Redis vs PostgreSQL (feature serving)

Fair setup: same 1M/5M feature keys, same JSON payload, same 10 batches of 1,000
lookups, same number of round trips and 3 measured runs after 1 warm-up. Redis
uses `maxmemory=4gb` and does not evict; PostgreSQL stores JSONB on disk.

| Keys | Redis load | PG load | Redis p50/batch | PG p50/batch | Hit rate |
|---:|---:|---:|---:|---:|---:|
| 1,000,000 | 23.10 s | 20.27 s | 6.93 ms | 51.37 ms | 100% |
| 5,000,000 | 121.79 s | 99.43 s | 8.13 ms | 66.54 ms | 100% |

At 5M, Redis uses 2.38 GB and PostgreSQL uses 2,849 MB. Redis is ~7.4× faster
at 1M and ~8.2× faster at 5M for the same batch.

**Memory-pressure side experiment:** with Redis capped at 512 MB, 5M keys do not
fit. Redis evicts 3.93M keys, serves only 21.68% of lookups and its p50 of
147.9 ms is therefore not comparable with PostgreSQL serving 100% of keys.

**Conclusion.** Redis is substantially faster while the complete working set
fits in RAM. When it does not fit, Redis requires more memory, Redis Cluster or
a disk-backed store.

## Pair A — Spark Structured Streaming vs Flink

Same Kafka topic (`bench.events3`), same 100,000 events, same filter
(`score > 0.5`), both sinks to Kafka. Output sets match exactly: 49,913 rows,
0 missing on either side.

| Engine | Job runtime | Submit → output | Input throughput | Output throughput |
|---|---:|---:|---:|---:|
| Flink 1.19 SQL | 9.16 s | 22 s | 10,917 ev/s | 5,449 ev/s |
| Spark 3.5 Structured Streaming | 9.0 s | 44 s | 11,111 ev/s | 5,546 ev/s |

`submit → output` includes SQL-client/JAR startup and is not a like-for-like
latency metric; `job runtime` is the fair processing comparison. This table
covers the bounded filter pipeline; the 7-day alert window is a separate SLA
experiment and is not represented by these numbers.

## Notes

- Full 5 GiB files are in `benchmarks/alternatives/data/` (gitignored).
- Raw per-run metrics: `olap/query_latency_*.json`, `feature_store/lookup_*.json`.
- Load timings: `*/load_*.json`; summary CSVs next to this file.
- These are local single-node observations, not production capacity claims.
