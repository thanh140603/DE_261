# Alternative-stack benchmark — results

Environment: [environment.json](environment.json)
Host: AMD Ryzen 7 8745H, 16 vCPU, 7.4–11 GiB WSL2 allocation, Ubuntu 26.04, Docker 29.9.2.
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

Concurrency on the same 1M-row selective query (p95 / throughput):

| Clients | PostgreSQL | ClickHouse |
|---:|---:|---:|
| 1 | 109 ms / 9.3 qps | 12 ms / 79.6 qps |
| 5 | 276 ms / 17.8 qps | 64 ms / 77.3 qps |
| 10 | 437 ms / 22.7 qps | 42 ms / 216.9 qps |

Active storage: PostgreSQL 200.9 MB vs ClickHouse 32.3 MB (~6.2× smaller).

**Conclusion.** PostgreSQL remains the right transactional/serving store for small
marts, but its row-store aggregation degrades quickly with scale. ClickHouse
(MPP/columnar) is clearly better from 1M rows onward. StarRocks was not installed
on this host; ClickHouse is the documented fallback, not a StarRocks measurement.

## Pair C — Data layout: partition vs Z-order/liquid clustering

Same 10M fact rows, same four filters, Spark local. p50 includes plan/launch
overhead, so compare relative values only.

| Layout | Date | Course | Org | Combined | Active files |
|---|---:|---:|---:|---:|---:|
| Partition by date | 499 ms | 927 ms | 579 ms | 356 ms | 41 |
| Partition + Z-order | 331 ms | 597 ms | 782 ms | 325 ms | 41 |
| Liquid clustering | 393 ms | 495 ms | 497 ms | 395 ms | 2 |

No layout wins every query: partition wins date-only, Z-order wins date/combined,
liquid wins course/org. Z-order and liquid require rewrite/OPTIMIZE time; partition
is cheaper to write but scans all files for non-date filters.

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
- Raw per-run metrics: `olap/query_latency_*.json`, `layout/layout_*.json`, `streaming/summary.json`.
- Load timings: `*/load_*.json`; summary CSVs next to this file.
- These are local single-node observations, not production capacity claims.
