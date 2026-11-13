"""Consume change events from the Debezium bench topic."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from confluent_kafka import Consumer

from benchmarks.cdc.metrics import summarize, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default="bench.bench.cdc_source")
    parser.add_argument("--bootstrap", default="localhost:9092")
    parser.add_argument("--group", default="bench-cdc-observer")
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    consumer = Consumer(
        {
            "bootstrap.servers": args.bootstrap,
            "group.id": args.group,
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([args.topic])
    ready = args.out.with_suffix(args.out.suffix + ".ready")
    ready.parent.mkdir(parents=True, exist_ok=True)
    ready.unlink(missing_ok=True)
    assignment_deadline = time.monotonic() + 10
    while not consumer.assignment() and time.monotonic() < assignment_deadline:
        consumer.poll(0.1)
    ready.write_text("ready\n")

    events: list[dict[str, object]] = []
    deadline = time.monotonic() + args.duration
    while time.monotonic() < deadline:
        message = consumer.poll(0.5)
        if message is None:
            continue
        if message.error():
            continue
        payload = json.loads(message.value())
        payload = payload.get("payload", payload)
        op = payload.get("__op") or payload.get("op")
        source_ms = payload.get("__ts_ms") or payload.get("ts_ms")
        latency_ms = None
        if source_ms is not None:
            latency_ms = max(0.0, time.time() * 1000 - float(source_ms))
        events.append(
            {
                "id": payload.get("id"),
                "op": op,
                "observed_at": time.time(),
                "latency_ms": latency_ms,
            }
        )
    consumer.close()

    deletes = sum(1 for event in events if event["op"] == "d")
    updates = sum(1 for event in events if event["op"] in {"u", "c"})
    latencies = [float(event["latency_ms"]) for event in events if event["latency_ms"] is not None]
    payload = {
        "engine": "debezium",
        "events": len(events),
        "updates": updates,
        "deletes": deletes,
        "latency_ms": summarize(latencies),
        "sample": events[:5],
    }
    write_json(args.out, payload)
    print(json.dumps({k: v for k, v in payload.items() if k != "sample"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
