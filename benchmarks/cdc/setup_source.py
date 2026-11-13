"""Create a 100k-row CDC source table in PostgreSQL."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import psycopg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--dsn", default="postgresql://lms:lms@localhost:5433/lms")
    args = parser.parse_args()

    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS bench")
        cur.execute("DROP TABLE IF EXISTS bench.cdc_source")
        cur.execute(
            """
            CREATE TABLE bench.cdc_source (
                id text PRIMARY KEY,
                org_id text NOT NULL,
                course_id text NOT NULL,
                learner_pseudonym text NOT NULL,
                score double precision NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
            )
            """
        )
        with (
            args.csv.open(newline="", encoding="utf-8") as source,
            cur.copy(
                "COPY bench.cdc_source (id, org_id, course_id, learner_pseudonym, score) FROM STDIN"
            ) as copy,
        ):
            reader = csv.DictReader(source)
            for index, row in enumerate(reader):
                if index >= args.rows:
                    break
                copy.write_row(
                    (
                        row["fact_id"],
                        row["org_id"],
                        row["course_id"],
                        row["learner_pseudonym"],
                        row["score"],
                    )
                )
        conn.commit()
    print(f"created bench.cdc_source with up to {args.rows} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
