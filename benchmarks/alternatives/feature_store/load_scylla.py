"""Load feature JSONL into ScyllaDB (CQL) for the feature-store benchmark."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from cassandra.cluster import Cluster
from cassandra.concurrent import execute_concurrent

from benchmarks.alternatives.common.metrics import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9042)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    cluster = Cluster([args.host], port=args.port)
    session = cluster.connect()
    session.execute(
        "CREATE KEYSPACE IF NOT EXISTS bench "
        "WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}"
    )
    session.execute("DROP TABLE IF EXISTS bench.features")
    session.execute(
        "CREATE TABLE bench.features (learner_pseudonym text PRIMARY KEY, payload text)"
    )
    prepared = session.prepare(
        "INSERT INTO bench.features (learner_pseudonym, payload) VALUES (?, ?)"
    )

    started = time.perf_counter()
    rows = 0
    pending: list[tuple[str, str]] = []
    with args.jsonl.open(encoding="utf-8") as source:
        for line in source:
            payload = json.loads(line)
            pending.append((payload["learner_pseudonym"], line.rstrip("\n")))
            rows += 1
            if len(pending) >= 1000:
                execute_concurrent(
                    session,
                    [(prepared, item) for item in pending],
                    concurrency=128,
                    raise_on_first_error=True,
                )
                pending.clear()
    if pending:
        execute_concurrent(
            session,
            [(prepared, item) for item in pending],
            concurrency=128,
            raise_on_first_error=True,
        )
    elapsed = time.perf_counter() - started
    result = {
        "engine": "scylla",
        "file": str(args.jsonl),
        "rows": rows,
        "seconds": round(elapsed, 3),
    }
    if args.out:
        write_json(args.out, result)
    print(json.dumps(result, indent=2))
    cluster.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
