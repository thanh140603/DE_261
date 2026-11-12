"""Measure ScyllaDB point lookups for the feature-store benchmark."""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from cassandra.cluster import Cluster
from cassandra.concurrent import execute_concurrent

from benchmarks.alternatives.common.metrics import summarize, write_json


def key(index: int) -> str:
    return f"k1_{index:024x}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--ops", type=int, default=10_000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9042)
    parser.add_argument(
        "--out", type=Path, default=Path("benchmarks/alternatives/results/feature_store")
    )
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    rng = random.Random(42)
    keys = list(dict.fromkeys(key(rng.randrange(args.rows)) for _ in range(args.ops)))
    cluster = Cluster([args.host], port=args.port)
    session = cluster.connect("bench")
    prepared = session.prepare("SELECT payload FROM bench.features WHERE learner_pseudonym = ?")

    samples: list[float] = []
    hits = 0
    for _ in range(args.repeat):
        started = time.perf_counter()
        results = execute_concurrent(
            session,
            [(prepared, (item,)) for item in keys],
            concurrency=64,
            raise_on_first_error=True,
        )
        samples.append((time.perf_counter() - started) * 1000)
        hits += sum(1 for ok, _ in results if ok)
    cluster.shutdown()

    payload = {
        "rows": args.rows,
        "ops": len(keys),
        "repeat": args.repeat,
        "scylla": summarize(samples),
        "hit_rate": round(hits / (args.repeat * len(keys)), 4),
        "raw_ms": samples,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / f"lookup_scylla_{args.label}.json", payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
