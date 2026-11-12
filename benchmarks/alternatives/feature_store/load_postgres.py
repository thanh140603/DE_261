"""Load feature JSONL into PostgreSQL as the disk-backed comparison store."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import psycopg

from benchmarks.alternatives.common.metrics import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    parser.add_argument(
        "--dsn",
        default=os.getenv("EDU_BENCH_POSTGRES_DSN", "postgresql://lms:lms@localhost:5433/lms"),
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    started = time.perf_counter()
    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS bench")
        cur.execute("DROP TABLE IF EXISTS bench.features")
        cur.execute(
            "CREATE TABLE bench.features ("
            "learner_pseudonym text PRIMARY KEY, payload jsonb NOT NULL)"
        )
        with (
            args.jsonl.open(encoding="utf-8") as source,
            cur.copy("COPY bench.features (learner_pseudonym, payload) FROM STDIN") as copy,
        ):
            for line in source:
                payload = json.loads(line)
                copy.write_row((payload["learner_pseudonym"], line.rstrip("\n")))
        conn.commit()
    elapsed = time.perf_counter() - started
    result = {"engine": "postgres", "file": str(args.jsonl), "seconds": round(elapsed, 3)}
    if args.out:
        write_json(args.out, result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
