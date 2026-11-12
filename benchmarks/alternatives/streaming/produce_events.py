"""Produce generated JSONL events to the benchmark Kafka topic."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from confluent_kafka import Producer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--topic", default="bench.events")
    parser.add_argument("--bootstrap", default="localhost:9092")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    producer = Producer({"bootstrap.servers": args.bootstrap, "linger.ms": 10})
    started = time.perf_counter()
    produced = 0
    with args.jsonl.open(encoding="utf-8") as source:
        for line in source:
            if args.limit and produced >= args.limit:
                break
            payload = json.loads(line)
            producer.produce(args.topic, key=payload["learner_pseudonym"], value=line.rstrip("\n"))
            produced += 1
            if produced % 10_000 == 0:
                producer.poll(0)
    producer.flush()
    elapsed = time.perf_counter() - started
    print(f"produced {produced} events in {elapsed:.3f}s ({produced / elapsed:,.0f}/s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
