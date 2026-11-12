"""Load the generated org-facts CSV into PostgreSQL for the OLAP benchmark."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import psycopg

from benchmarks.alternatives.common.metrics import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--dsn",
        default=os.getenv("EDU_BENCH_POSTGRES_DSN", "postgresql://lms:lms@localhost:5433/lms"),
    )
    args = parser.parse_args()

    dsn = args.dsn
    started = time.perf_counter()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS bench")
            cur.execute(
                """
                DROP TABLE IF EXISTS bench.org_facts;
                CREATE TABLE bench.org_facts (
                    fact_id text PRIMARY KEY,
                    org_id text NOT NULL,
                    learner_pseudonym text NOT NULL,
                    course_id text NOT NULL,
                    enrollment_id text NOT NULL,
                    event_date date NOT NULL,
                    completed boolean NOT NULL,
                    score double precision NOT NULL,
                    mastery double precision NOT NULL
                )
                """
            )
            with (
                args.csv.open("rb") as source,
                cur.copy("COPY bench.org_facts FROM STDIN WITH (FORMAT CSV, HEADER TRUE)") as copy,
            ):
                while chunk := source.read(1024 * 1024):
                    copy.write(chunk)
        conn.commit()
    elapsed = time.perf_counter() - started
    payload = {"engine": "postgres", "file": str(args.csv), "seconds": round(elapsed, 3)}
    if args.out:
        write_json(args.out, payload)
    print(f"postgres loaded {args.csv} in {elapsed:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
