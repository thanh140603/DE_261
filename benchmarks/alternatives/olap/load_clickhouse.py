"""Load the generated org-facts CSV into ClickHouse for the OLAP benchmark."""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

from benchmarks.alternatives.common.metrics import write_json

CONTAINER = "de261-bench-clickhouse"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    # The CSV is mounted read-only at /data in the benchmark container.
    container_path = "/data/" + args.csv.name
    ddl = """
    CREATE DATABASE IF NOT EXISTS bench;
    DROP TABLE IF EXISTS bench.org_facts;
    CREATE TABLE bench.org_facts (
        fact_id String,
        org_id LowCardinality(String),
        learner_pseudonym String,
        course_id LowCardinality(String),
        enrollment_id String,
        event_date Date,
        completed UInt8,
        score Float64,
        mastery Float64
    ) ENGINE = MergeTree ORDER BY (org_id, course_id, event_date);
    """
    subprocess.run(
        ["docker", "exec", CONTAINER, "clickhouse-client", "--query", ddl],
        check=True,
    )

    started = time.perf_counter()
    with args.csv.open("rb") as source:
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                CONTAINER,
                "clickhouse-client",
                "--query",
                "INSERT INTO bench.org_facts FORMAT CSVWithNames",
            ],
            stdin=source,
            check=True,
        )
    elapsed = time.perf_counter() - started
    payload = {"engine": "clickhouse", "file": str(container_path), "seconds": round(elapsed, 3)}
    if args.out:
        write_json(args.out, payload)
    print(f"clickhouse loaded {container_path} in {elapsed:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
