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

## Pair C — Redis vs PostgreSQL disk store (feature serving)

Same `features` JSONL, 1M/5M keys. Redis is capped at **512 MiB** with
`allkeys-lru` to simulate a working set larger than memory; PostgreSQL stores
the payload as JSONB on disk. Workload: ~10,000 distinct point lookups per run,
3 measured runs after 1 warm-up.

| Keys | Redis load | PostgreSQL load | Redis p50 | PG p50 | Redis hit rate | Evicted |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000,000 | 24.43 s | 20.27 s | 161.8 ms | 548.5 ms | 100.0% | 0 |
| 5,000,000 | 131.38 s | 99.43 s | 147.9 ms | 657.9 ms | 21.68% | 3,926,686 |

Redis at 1M keys uses 477.7 MiB and fits under the cap. At 5M keys it reaches
512 MiB, evicts 3.93M keys and serves only 21.68% of lookups; its latency number
therefore excludes most misses. PostgreSQL serves 100% of keys but is ~4× slower
per 10k-key batch.

ScyllaDB 6.2 single-node loaded 1M keys in 142.23 s (1 GB memory, 1 vCPU) and
5M keys in 702.39 s (2 GB memory, 2 vCPU). The 10k-key batch had p50 5,021.6 ms
at 1M and 5,004.6 ms at 5M, with 100% hit rate at both sizes. At this single-node
size it does not beat PostgreSQL; its value is keeping the complete working set
on disk and scaling horizontally.

**Conclusion.** Redis is correct and fast only while the working set fits in its
memory budget. At 5M keys the capped instance cannot serve the feature store
completely; a disk-backed store is required or Redis must be scaled out.

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
