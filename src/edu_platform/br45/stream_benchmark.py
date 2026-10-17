"""Isolated normalized-Kafka -> Spark -> PostgreSQL window benchmark, with batch oracle.

CDC-to-alert latency is measured separately by verify.py. This experiment does not
claim its directly published synthetic messages passed through PostgreSQL CDC.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from confluent_kafka import Producer

from .config import settings
from .contracts import timestamp
from .db import connect, state
from .verify import wait_for


def run(
    output: str = "docs/evidence/br45",
    sizes: tuple[int, ...] = (1000, 10000, 100000),
    repetitions: int = 3,
) -> list[dict[str, Any]]:
    cfg = settings()
    producer = Producer(
        {
            "bootstrap.servers": cfg.kafka,
            "enable.idempotence": True,
            "queue.buffering.max.messages": 200000,
        }
    )
    with connect() as conn:
        at = timestamp(state(conn, "evaluation_clock"))
    results: list[dict[str, Any]] = []
    dest = Path(output)
    dest.mkdir(parents=True, exist_ok=True)
    for size in sizes:
        for repeat in range(repetitions):
            student = "br45-benchmark-" + uuid.uuid4().hex[:12]
            events: list[dict[str, Any]] = []
            for i in range(size):
                event_time = at - timedelta(seconds=1 + (i * 7919) % (14 * 86400))
                events.append(
                    {
                        "event_id": student + f"-{i}",
                        "student_id": student,
                        "course_id": "c-py-201",
                        "event_time": event_time.isoformat(),
                        "delta": 1,
                        "kind": "activity",
                    }
                )
            # Stable duplicate ids are an input to both alternatives.
            messages = events + events[::100]
            for index, t in enumerate((at, at - timedelta(days=7))):
                messages.append(
                    {
                        "event_id": student + f"-tick-{index}",
                        "student_id": student,
                        "course_id": "c-py-201",
                        "event_time": (t - timedelta(milliseconds=1)).isoformat(),
                        "delta": 0,
                        "kind": "clock",
                    }
                )
            started = time.perf_counter()
            unique = {e["event_id"]: e for e in messages}.values()
            recent = sum(
                e["delta"]
                for e in unique
                if at - timedelta(days=7) <= timestamp(e["event_time"]) < at
            )
            previous = sum(
                e["delta"]
                for e in unique
                if at - timedelta(days=14) <= timestamp(e["event_time"]) < at - timedelta(days=7)
            )
            batch_ms = (time.perf_counter() - started) * 1000
            offsets: dict[str, int] = {}
            errors: list[str] = []

            def delivered(
                error: Any, msg: Any, errors: list[str] = errors, offsets: dict[str, int] = offsets
            ) -> None:
                if error:
                    errors.append(str(error))
                else:
                    key = str(msg.partition())
                    offsets[key] = max(offsets.get(key, 0), msg.offset() + 1)

            started = time.perf_counter()
            for event in messages:
                producer.produce(
                    cfg.activity_topic, key=student, value=json.dumps(event), on_delivery=delivered
                )
            assert producer.flush(60) == 0 and not errors, errors
            publish_ms = (time.perf_counter() - started) * 1000

            def complete(
                offsets: dict[str, int] = offsets,
                student: str = student,
                recent: int = recent,
                previous: int = previous,
            ) -> bool:
                with connect() as conn:
                    progress = state(conn, "spark_progress") or {}
                    end = progress.get("sources", [{}])[0].get("endOffset", {})
                    if isinstance(end, str):
                        end = json.loads(end)
                    consumed = end.get(cfg.activity_topic, {})
                    if not all(consumed.get(k, 0) >= v for k, v in offsets.items()):
                        return False
                    counts = {
                        r["window_end"]: r["activity_count"]
                        for r in conn.execute(
                            (
                                "SELECT window_end,activity_count FROM "
                                "analytics.activity_windows WHERE student_id=%s AND "
                                "window_end=ANY(%s)"
                            ),
                            (student, [at, at - timedelta(days=7)]),
                        )
                    }
                    assert (
                        counts.get(at) == recent and counts.get(at - timedelta(days=7)) == previous
                    ), (counts, recent, previous)
                    return True

            wait_for(
                complete,
                f"{size} synthetic normalized Kafka events must match the batch window baseline",
                timeout=300,
            )
            elapsed = (time.perf_counter() - started) * 1000
            result = {
                "measured_at": datetime.now(UTC).isoformat(),
                "unique_events": size,
                "input_messages": len(messages),
                "repeat": repeat + 1,
                "publish_ms": publish_ms,
                "kafka_to_persisted_windows_ms": elapsed,
                "unique_events_per_second": size / (elapsed / 1000),
                "python_batch_ms": batch_ms,
                "recent_count": recent,
                "previous_count": previous,
                "correct": True,
                "scope": "normalized Kafka->Spark->PostgreSQL; excludes CDC and risk",
            }
            results.append(result)
            with (dest / "br5_stream_benchmark.csv").open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=list(result))
                writer.writeheader()
                writer.writerows(results)
            print(
                (
                    "BR5 "
                    f"{size}"
                    " unique events repetition "
                    f"{repeat + 1}"
                    ": "
                    f"{elapsed:.1f}"
                    " ms, "
                    f"{result['unique_events_per_second']:.1f}"
                    " events/s; batch="
                    f"{batch_ms:.2f}"
                    "ms"
                ),
                flush=True,
            )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/evidence/br45")
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    run(args.output, repetitions=args.repetitions)
