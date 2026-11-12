"""Prepare the 100k-event Kafka input used by the Spark/Flink filter benchmark.

Adds an ``ingest_time`` epoch-millisecond field and flattens the ISO timestamp
to the ``yyyy-MM-dd HH:mm:ss`` form both SQL engines parse consistently.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "jsonl",
        type=Path,
        nargs="?",
        default=Path("benchmarks/alternatives/data/events-100k.jsonl"),
    )
    parser.add_argument(
        "--out", type=Path, default=Path("benchmarks/alternatives/data/events-100k-ingest.jsonl")
    )
    parser.add_argument("--limit", type=int, default=100_000)
    args = parser.parse_args()

    ingest_time = int(time.time() * 1000)
    rows = matched = 0
    with args.jsonl.open(encoding="utf-8") as source, args.out.open("w", encoding="utf-8") as sink:
        for line in source:
            if rows >= args.limit:
                break
            payload = json.loads(line)
            payload["ingest_time"] = ingest_time
            payload["occurred_at"] = payload["occurred_at"].replace("T", " ")[:19]
            sink.write(json.dumps(payload, separators=(",", ":")) + "\n")
            rows += 1
            matched += payload["score"] > 0.5
    print(f"wrote {rows} rows to {args.out}; expected matched={matched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
