"""Concurrency and storage-footprint check for PostgreSQL vs ClickHouse."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psycopg

from benchmarks.alternatives.common.metrics import summarize, write_json

FILTER = "event_date = '2026-10-15'"
PG_SQL = f"""
SELECT org_id, course_id, count(*) AS rows, avg(score)::float8 AS avg_score
FROM bench.org_facts
WHERE {FILTER}
GROUP BY org_id, course_id
ORDER BY org_id, course_id
"""
CH_SQL = f"""
SELECT org_id, course_id, count(*) AS rows, avg(score) AS avg_score
FROM bench.org_facts
WHERE {FILTER}
GROUP BY org_id, course_id
ORDER BY org_id, course_id
FORMAT JSON
"""


def pg_query(dsn: str) -> tuple[int, float]:
    started = time.perf_counter()
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(PG_SQL)
        rows = cur.fetchall()
    return len(rows), (time.perf_counter() - started) * 1000


def ch_query(url: str) -> tuple[int, float]:
    started = time.perf_counter()
    req = urllib.request.Request(
        url + "/?" + urllib.parse.urlencode({"database": "bench"}),
        data=CH_SQL.encode("utf-8"),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as response:
        payload = json.loads(response.read())
    return len(payload["data"]), (time.perf_counter() - started) * 1000


def run_engine(name: str, fn: Any, concurrency: int) -> dict[str, Any]:
    lock = threading.Lock()
    samples: list[float] = []
    errors = 0

    def task() -> None:
        nonlocal errors
        try:
            _, ms = fn()
            with lock:
                samples.append(ms)
        except Exception:
            with lock:
                errors += 1

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(lambda _: task(), range(concurrency)))
    wall_s = time.perf_counter() - started
    return {
        "engine": name,
        "concurrency": concurrency,
        "wall_s": round(wall_s, 3),
        "throughput_qps": round(concurrency / wall_s, 3),
        "errors": errors,
        "latency": summarize(samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", default="1,5,10")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument(
        "--dsn",
        default=os.getenv("EDU_BENCH_POSTGRES_DSN", "postgresql://lms:lms@localhost:5433/lms"),
    )
    parser.add_argument("--clickhouse-url", default="http://localhost:8123")
    parser.add_argument("--out", type=Path, default=Path("benchmarks/alternatives/results/olap"))
    parser.add_argument("--label", default="1m")
    args = parser.parse_args()

    pg = lambda: pg_query(args.dsn)  # noqa: E731
    ch = lambda: ch_query(args.clickhouse_url)  # noqa: E731
    pg()
    ch()

    levels = [int(item) for item in args.concurrency.split(",")]
    results: list[dict[str, Any]] = []
    for level in levels:
        for _ in range(args.repeat):
            results.append(run_engine("postgres", pg, level))
            results.append(run_engine("clickhouse", ch, level))

    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_total_relation_size('bench.org_facts')")
        pg_bytes = int(cur.fetchone()[0])
    ch_storage = (
        urllib.request.urlopen(
            args.clickhouse_url
            + "/?"
            + urllib.parse.urlencode(
                {
                    "database": "bench",
                    "query": (
                        "SELECT sum(bytes_on_disk) FROM system.parts "
                        "WHERE database='bench' AND table='org_facts' AND active"
                    ),
                }
            )
        )
        .read()
        .decode()
        .strip()
    )

    payload = {
        "label": args.label,
        "query": PG_SQL.strip(),
        "concurrency": levels,
        "repeat": args.repeat,
        "runs": results,
        "storage": {"postgres_bytes": pg_bytes, "clickhouse_bytes": int(ch_storage)},
    }
    write_json(args.out / f"concurrency_{args.label}.json", payload)
    print(json.dumps(payload["storage"], indent=2))
    for run in results:
        print(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
