"""Measure Memcached point lookups with the same batch shape as Redis."""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from pymemcache.client.base import Client

from benchmarks.alternatives.common.metrics import summarize, write_json


def key(index: int) -> str:
    return f"k1_{index:024x}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--ops", type=int, default=10_000)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11211)
    parser.add_argument(
        "--out", type=Path, default=Path("benchmarks/alternatives/results/feature_store")
    )
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    rng = random.Random(42)
    keys = list(dict.fromkeys(key(rng.randrange(args.rows)) for _ in range(args.ops)))
    batches = [keys[i : i + args.batch_size] for i in range(0, len(keys), args.batch_size)]
    client = Client((args.host, args.port))

    timings: list[float] = []
    hits = 0
    for _ in range(args.repeat):
        for batch in batches:
            started = time.perf_counter()
            found = client.get_many(["bench:feature:" + item for item in batch])
            timings.append((time.perf_counter() - started) * 1000)
            hits += len(found)

    payload = {
        "rows": args.rows,
        "keys": len(keys),
        "batches": len(batches),
        "batch_size": args.batch_size,
        "repeat": args.repeat,
        "memcached": summarize(timings),
        "hit_rate": round(hits / (args.repeat * len(keys)), 4),
        "raw_ms": timings,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / f"lookup_memcached_{args.label}.json", payload)
    print(json.dumps(payload, indent=2))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
