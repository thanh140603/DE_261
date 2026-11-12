"""Fair Redis vs PostgreSQL point-lookup benchmark.

Both engines receive the same key batches, same batch size, same number of
round trips and the same number of measured runs. Redis uses MGET; PostgreSQL
uses one ``= ANY(array)`` query per batch.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path
from typing import Any

import psycopg
import redis

from benchmarks.alternatives.common.metrics import summarize, write_json


def key(index: int) -> str:
    return f"k1_{index:024x}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--ops", type=int, default=10_000)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--redis-port", type=int, default=6381)
    parser.add_argument(
        "--dsn",
        default=os.getenv("EDU_BENCH_POSTGRES_DSN", "postgresql://lms:lms@localhost:5433/lms"),
    )
    parser.add_argument(
        "--out", type=Path, default=Path("benchmarks/alternatives/results/feature_store")
    )
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    rng = random.Random(42)
    keys = list(dict.fromkeys(key(rng.randrange(args.rows)) for _ in range(args.ops)))
    batches = [keys[i : i + args.batch_size] for i in range(0, len(keys), args.batch_size)]
    redis_client = redis.Redis(host="127.0.0.1", port=args.redis_port, decode_responses=True)

    timings: dict[str, list[float]] = {"redis": [], "postgres": []}
    hits = {"redis": 0, "postgres": 0}

    def run_once() -> None:
        for batch in batches:
            started = time.perf_counter()
            values = redis_client.mget(["bench:feature:" + item for item in batch])
            timings["redis"].append((time.perf_counter() - started) * 1000)
            hits["redis"] += sum(value is not None for value in values)

            with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
                started = time.perf_counter()
                cur.execute(
                    "SELECT learner_pseudonym, payload FROM bench.features "
                    "WHERE learner_pseudonym = ANY(%s)",
                    (batch,),
                )
                rows = cur.fetchall()
                timings["postgres"].append((time.perf_counter() - started) * 1000)
                hits["postgres"] += len(rows)

    run_once()  # warm-up
    timings["redis"].clear()
    timings["postgres"].clear()
    hits = {"redis": 0, "postgres": 0}
    for _ in range(args.repeat):
        run_once()

    total = args.repeat * len(keys)
    memory = redis_client.info("memory")
    result: dict[str, Any] = {
        "rows": args.rows,
        "keys": len(keys),
        "batches": len(batches),
        "batch_size": args.batch_size,
        "repeat": args.repeat,
        "redis": summarize(timings["redis"]),
        "postgres": summarize(timings["postgres"]),
        "redis_hit_rate": round(hits["redis"] / total, 4),
        "postgres_hit_rate": round(hits["postgres"] / total, 4),
        "redis_used_memory": memory.get("used_memory_human"),
        "redis_maxmemory": memory.get("maxmemory_human"),
        "raw_ms": timings,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / f"lookup_fair_{args.label}.json", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
