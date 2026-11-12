"""Compare Redis (capped) and PostgreSQL for point feature lookups."""

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


def _key(index: int) -> str:
    return f"k1_{index:024x}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, required=True, help="number of loaded keys")
    parser.add_argument("--ops", type=int, default=10_000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--redis-port", type=int, default=6380)
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
    keys = list(dict.fromkeys(_key(rng.randrange(args.rows)) for _ in range(args.ops)))
    redis_client = redis.Redis(host="127.0.0.1", port=args.redis_port, decode_responses=True)
    timings: dict[str, list[float]] = {"redis": [], "postgres": []}
    hits = 0
    pg_hits = 0

    for _ in range(args.repeat):
        started = time.perf_counter()
        pipe = redis_client.pipeline(transaction=False)
        for key in keys:
            pipe.get("bench:feature:" + key)
        values = pipe.execute()
        timings["redis"].append((time.perf_counter() - started) * 1000)
        hits += sum(value is not None for value in values)

        with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
            started = time.perf_counter()
            cur.execute(
                "SELECT learner_pseudonym, payload FROM bench.features "
                "WHERE learner_pseudonym = ANY(%s)",
                (keys,),
            )
            pg_rows = cur.fetchall()
            timings["postgres"].append((time.perf_counter() - started) * 1000)
            pg_hits += len(pg_rows)

    result: dict[str, Any] = {
        "rows": args.rows,
        "ops": len(keys),
        "repeat": args.repeat,
        "redis": summarize(timings["redis"]),
        "postgres": summarize(timings["postgres"]),
        "redis_hit_rate": round(hits / (args.repeat * len(keys)), 4),
        "postgres_hit_rate": round(pg_hits / (args.repeat * len(keys)), 4),
        "raw_ms": timings,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / f"lookup_{args.label}.json", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
