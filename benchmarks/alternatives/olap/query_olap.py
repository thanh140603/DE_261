"""Run the same org-progress aggregation on PostgreSQL and ClickHouse."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import psycopg

from benchmarks.alternatives.common.metrics import summarize, write_json

PG_SQL = """
SELECT org_id, course_id,
       count(*) AS rows,
       count(DISTINCT learner_pseudonym) AS learners,
       avg(score)::float8 AS avg_score,
       avg(mastery)::float8 AS avg_mastery,
       sum(CASE WHEN completed THEN 1 ELSE 0 END)::bigint AS completed
FROM bench.org_facts
GROUP BY org_id, course_id
ORDER BY org_id, course_id
"""

CH_SQL = """
SELECT org_id, course_id,
       count(*) AS rows,
       uniqExact(learner_pseudonym) AS learners,
       avg(score) AS avg_score,
       avg(mastery) AS avg_mastery,
       sum(completed) AS completed
FROM bench.org_facts
GROUP BY org_id, course_id
ORDER BY org_id, course_id
"""


def pg_rows(dsn: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(PG_SQL)
        return list(cur.fetchall())


def ch_rows(url: str) -> list[tuple[Any, ...]]:
    query = CH_SQL + " FORMAT JSON"
    req = urllib.request.Request(
        url + "/?" + urllib.parse.urlencode({"database": "bench"}),
        data=query.encode("utf-8"),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as response:
        payload = json.loads(response.read())
    return [
        (
            row["org_id"],
            row["course_id"],
            row["rows"],
            row["learners"],
            row["avg_score"],
            row["avg_mastery"],
            row["completed"],
        )
        for row in payload["data"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["postgres", "clickhouse", "both"], default="both")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument(
        "--dsn",
        default=os.getenv("EDU_BENCH_POSTGRES_DSN", "postgresql://lms:lms@localhost:5433/lms"),
    )
    parser.add_argument("--clickhouse-url", default="http://localhost:8123")
    parser.add_argument("--out", type=Path, default=Path("benchmarks/alternatives/results/olap"))
    parser.add_argument("--label", default="1m", help="dataset label used in the result filename")
    args = parser.parse_args()

    engines = ["postgres", "clickhouse"] if args.engine == "both" else [args.engine]
    rows_by_engine: dict[str, list[tuple[Any, ...]]] = {}
    timings: dict[str, list[float]] = {}
    for engine in engines:
        fn = pg_rows if engine == "postgres" else ch_rows
        kwargs = {"dsn": args.dsn} if engine == "postgres" else {"url": args.clickhouse_url}
        # Warm-up then measured runs.
        fn(**kwargs)
        samples: list[float] = []
        for _ in range(args.repeat):
            started = time.perf_counter()
            rows_by_engine[engine] = fn(**kwargs)
            samples.append((time.perf_counter() - started) * 1000)
        timings[engine] = samples
        print(f"{engine}: {summarize(samples)}")

    if len(rows_by_engine) == 2:
        left = rows_by_engine["postgres"]
        right = rows_by_engine["clickhouse"]
        if len(left) != len(right):
            raise SystemExit(f"row count mismatch: postgres={len(left)} clickhouse={len(right)}")
        for a, b in zip(left, right, strict=True):
            for index in (2, 3, 6):
                if int(a[index]) != int(b[index]):
                    raise SystemExit(f"integer mismatch at {a[0]}/{a[1]}: {a[index]} != {b[index]}")
            for index in (4, 5):
                if abs(float(a[index]) - float(b[index])) > 1e-9:
                    raise SystemExit(f"float mismatch at {a[0]}/{a[1]}: {a[index]} != {b[index]}")
        print(f"correctness: {len(left)} groups match")

    payload = {
        "engines": engines,
        "repeat": args.repeat,
        "timings_ms": {name: summarize(values) for name, values in timings.items()},
        "raw_ms": timings,
        "groups": len(next(iter(rows_by_engine.values()))),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / f"query_latency_{args.label}.json", payload)
    print(json.dumps(payload["timings_ms"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
