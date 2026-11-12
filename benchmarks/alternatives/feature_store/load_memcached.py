"""Load feature JSONL into Memcached for the in-memory KV comparison."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pymemcache.client.base import Client

from benchmarks.alternatives.common.metrics import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11211)
    parser.add_argument("--prefix", default="bench:feature:")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    client = Client((args.host, args.port), default_noreply=False)
    client.flush_all()
    started = time.perf_counter()
    rows = 0
    batch: dict[str, bytes] = {}
    with args.jsonl.open(encoding="utf-8") as source:
        for line in source:
            payload = json.loads(line)
            batch[args.prefix + payload["learner_pseudonym"]] = line.rstrip("\n").encode("utf-8")
            rows += 1
            if len(batch) >= 1000:
                client.set_many(batch)
                batch.clear()
    if batch:
        client.set_many(batch)
    elapsed = time.perf_counter() - started
    result = {
        "engine": "memcached",
        "file": str(args.jsonl),
        "rows": rows,
        "seconds": round(elapsed, 3),
    }
    if args.out:
        write_json(args.out, result)
    print(json.dumps(result, indent=2))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
