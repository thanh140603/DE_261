"""Load feature JSONL into the capped Redis benchmark instance."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import redis

from benchmarks.alternatives.common.metrics import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6380)
    parser.add_argument("--prefix", default="bench:feature:")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    client = redis.Redis(host=args.host, port=args.port, decode_responses=True)
    client.flushdb()
    evicted_before = client.info("stats").get("evicted_keys", 0)
    started = time.perf_counter()
    pipeline = client.pipeline(transaction=False)
    rows = 0
    with args.jsonl.open(encoding="utf-8") as source:
        for line in source:
            payload = json.loads(line)
            pipeline.set(args.prefix + payload["learner_pseudonym"], line.rstrip("\n"))
            rows += 1
            if rows % 1000 == 0:
                pipeline.execute()
    pipeline.execute()
    elapsed = time.perf_counter() - started
    info = client.info("memory")
    stats = client.info("stats")
    evicted_after = stats.get("evicted_keys", 0)
    payload = {
        "engine": "redis",
        "file": str(args.jsonl),
        "rows": rows,
        "seconds": round(elapsed, 3),
        "used_memory": info.get("used_memory_human"),
        "maxmemory": info.get("maxmemory_human"),
        "evicted_keys": evicted_after - evicted_before,
        "evicted_keys_total": evicted_after,
    }
    if args.out:
        write_json(args.out, payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
