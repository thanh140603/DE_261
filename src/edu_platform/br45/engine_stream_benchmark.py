"""Matched Kafka window and source-to-Advisor trials for Spark and Flink."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

from confluent_kafka import Consumer, Producer, TopicPartition

from .config import settings
from .contracts import timestamp
from .db import connect, state
from .engine_benchmark import DAY, SIZES, Journal, api, require_isolation, wait
from .fixtures import upsert
from .oracle import windows
from .risk import persist, score

COURSE = "c-py-201"
ASSIGNMENT = "engine-bench-risk-due"
PAST = (8, 9, 10, 11)


class Observer:
    def __init__(self, engine: str, run: str, at: datetime) -> None:
        self.engine = engine
        self.run = run
        self.at = at
        self.ends = (at, at - 7 * DAY)
        cfg = settings()
        self.topic = cfg.activity_topic
        self.consumer = (
            Consumer(
                {
                    "bootstrap.servers": cfg.kafka,
                    "group.id": f"br45-flink-{run}",
                    "enable.auto.commit": False,
                }
            )
            if engine == "flink"
            else None
        )
        self.producer = Producer(
            {
                "bootstrap.servers": cfg.kafka,
                "enable.idempotence": True,
                "queue.buffering.max.messages": 200000,
            }
        )

    def close(self) -> None:
        if self.consumer:
            self.consumer.close()

    def send(self, records: list[dict[str, Any]]) -> dict[str, int]:
        offsets: dict[str, int] = {}
        errors: list[str] = []

        def delivered(error: Any, message: Any) -> None:
            if error:
                errors.append(str(error))
            else:
                partition = str(message.partition())
                offsets[partition] = max(offsets.get(partition, 0), message.offset() + 1)

        for record in records:
            self.producer.produce(
                self.topic,
                key=record["student_id"],
                value=json.dumps(record),
                on_delivery=delivered,
            )
        if self.producer.flush(60) or errors:
            raise RuntimeError(f"Kafka delivery failed: {errors[:2]}")
        return offsets

    def consumed(self, offsets: dict[str, int]) -> bool:
        if self.consumer:
            partitions = self.consumer.committed(
                [TopicPartition(self.topic, int(key)) for key in offsets],
                timeout=5,
            )
            return all(
                partition.offset >= offsets[str(partition.partition)] for partition in partitions
            )
        with connect() as conn:
            progress = state(conn, "spark_progress") or {}
        end = progress.get("sources", [{}])[0].get("endOffset", {})
        if isinstance(end, str):
            end = json.loads(end)
        found = (end or {}).get(self.topic, {})
        return all(found.get(key, 0) >= value for key, value in offsets.items())

    def confirmed(
        self,
        expected: dict[tuple[str, str, datetime], int],
        offsets: dict[str, int],
    ) -> bool:
        students = sorted({key[0] for key in expected})
        with connect() as conn:
            actual = {
                (row["student_id"], row["course_id"], row["window_end"]): row["activity_count"]
                for row in conn.execute(
                    "SELECT student_id,course_id,window_end,activity_count "
                    "FROM br45_benchmark.activity_windows WHERE run_id=%s AND engine=%s "
                    "AND student_id=ANY(%s) AND window_end=ANY(%s)",
                    (self.run, self.engine, students, list(self.ends)),
                )
            }
        return actual == expected and self.consumed(offsets)

    def verify(self, rows: list[dict[str, Any]], offsets: dict[str, int]) -> None:
        expected = windows(rows, list(self.ends))
        wait(lambda: self.confirmed(expected, offsets), "Kafka offset or window parity timed out")

    def output(self, student: str) -> tuple[int, int]:
        with connect() as conn:
            rows = {
                row["window_end"]: row["activity_count"]
                for row in conn.execute(
                    "SELECT window_end,activity_count FROM br45_benchmark.activity_windows "
                    "WHERE run_id=%s AND engine=%s AND student_id=%s AND course_id=%s "
                    "AND window_end=ANY(%s)",
                    (self.run, self.engine, student, COURSE, list(self.ends)),
                )
            }
        return rows[self.ends[0]], rows[self.ends[1]]


def event(student: str, key: str, at: datetime, delta: int = 1) -> dict[str, Any]:
    return {
        "event_id": f"{student}-{key}",
        "student_id": student,
        "course_id": COURSE,
        "event_time": at.isoformat(),
        "delta": delta,
        "kind": "activity" if delta else "clock",
    }


def workload(prefix: str, size: int, at: datetime) -> list[dict[str, Any]]:
    students = [f"{prefix}-{index}" for index in range(8)]
    events = [
        event(
            students[index % len(students)],
            str(index),
            at - timedelta(seconds=1 + index * 7919 % (14 * 86400)),
        )
        for index in range(size)
    ]
    return (
        events
        + events[::100]
        + [
            event(student, f"tick-{index}", end - timedelta(milliseconds=1), 0)
            for student in students
            for index, end in enumerate((at, at - 7 * DAY))
        ]
    )


def correctness(observer: Observer, prefix: str) -> dict[str, Any]:
    at = observer.at
    student = f"{prefix}-correctness"
    fresh = event(student, "new", at - DAY)
    prior = event(student, "previous", at - 8 * DAY)
    # End-boundary records contribute to the later interval only.
    boundary = event(student, "boundary", at - 7 * DAY)
    initial = [fresh, boundary, prior, fresh]
    observer.verify(initial, observer.send(initial))
    corrected = event(student, "retract", timestamp(prior["event_time"]), -1)
    replacement = event(student, "replacement", at - 2 * DAY)
    changes = [corrected, replacement, corrected]
    observer.verify(initial + changes, observer.send(changes))
    return {"checks": ["duplicate", "out_of_order", "half_open_window", "signed_retraction"]}


def restart_parity(observer: Observer, prefix: str) -> dict[str, Any]:
    at = observer.at
    student = f"{prefix}-correctness"
    assert observer.output(student) == (3, 0), "Prior committed window rows are missing"
    # Replaying an existing identity after restore must not add another occurrence.
    replayed = event(student, "replacement", at - 2 * DAY)
    extra = event(student, "after-restart", at - 4 * DAY)
    expected = {(student, COURSE, at): 4, (student, COURSE, at - 7 * DAY): 0}
    offsets = observer.send([replayed, extra])
    wait(lambda: observer.confirmed(expected, offsets), "Restored window or dedup state differs")
    return {"checks": ["checkpoint_window_state", "checkpoint_event_identity"]}


def normalized_offsets(student: str, minimum: int) -> dict[str, int] | None:
    with connect() as conn:
        landed = conn.execute(
            "SELECT count(*) FILTER (WHERE payload->>'kind'='activity') AS n, "
            "count(*) FILTER (WHERE payload->>'kind'='clock') AS ticks "
            "FROM analytics.outbox WHERE published_at IS NOT NULL AND payload->>'student_id'=%s",
            (student,),
        ).fetchone()
        assert landed is not None
        offsets: dict[str, int] | None = state(conn, "published_offsets")
        return offsets if landed["n"] >= minimum and landed["ticks"] else None


def score_persisted(observer: Observer, student: str, expected: int) -> None:
    recent, previous = observer.output(student)
    with connect() as conn:

        def rows(table: str) -> list[dict[str, Any]]:
            return [
                row["data"]
                for row in conn.execute(
                    "SELECT data FROM analytics.clean_rows WHERE table_name=%s AND NOT deleted "
                    "AND (data->>'student_id' IS NULL OR data->>'student_id'=%s)",
                    (table, student),
                )
            ]

        enrollment = rows("enrollments")[0]
        course = next(row for row in rows("courses") if row["id"] == COURSE)
        result = score(
            enrollment,
            course,
            rows("assignments"),
            rows("submissions"),
            rows("activity_events"),
            observer.at,
            recent,
            previous,
        )
        if result["score"] != expected:
            raise AssertionError(f"Risk score differs: {result['score']} != {expected}")
        persist(conn, result)


def risk_scenario(observer: Observer, student: str, recover: bool) -> dict[str, Any]:
    at = observer.at
    previous = [event(student, f"previous-{age}", at - age * DAY) for age in PAST]
    recent = [event(student, f"recent-{i}", at - timedelta(minutes=i)) for i in range(1, 5)]
    records = recent if recover else previous
    if not recover:
        with connect() as conn:
            upsert(
                conn,
                "enrollments",
                {
                    "id": f"{student}-enrollment",
                    "student_id": student,
                    "course_id": COURSE,
                    "status": "active",
                    "enrolled_at": at - 30 * DAY,
                },
            )

        def enrolled() -> bool:
            with connect() as conn:
                return (
                    conn.execute(
                        "SELECT 1 FROM analytics.clean_rows WHERE table_name='enrollments' "
                        "AND row_key=%s AND NOT deleted",
                        (f"{student}-enrollment",),
                    ).fetchone()
                    is not None
                )

        wait(enrolled, "Enrollment did not land through CDC")
        with connect() as conn:
            upsert(conn, "clocks", {"id": f"{student}-clock", "evaluated_at": at})
        wait(lambda: normalized_offsets(student, 0), "Clock tick did not publish")
    with connect() as conn:
        for row in records:
            upsert(
                conn,
                "activity_events",
                {
                    "id": row["event_id"],
                    "student_id": student,
                    "course_id": COURSE,
                    "event_type": "lesson_complete",
                    "event_time": row["event_time"],
                },
            )
    started = time.perf_counter()
    offsets = wait(
        lambda: normalized_offsets(student, 8 if recover else 4),
        "Debezium did not publish all normalized activity events",
    )
    # The persisted zero-weight clock refresh supplies an empty recent window at alert creation.
    zero = event(student, "clock", at - timedelta(milliseconds=1), 0)
    observer.verify(previous + (recent if recover else []) + [zero], offsets)
    expected = 50 if recover else 100
    score_persisted(observer, student, expected)

    def visible() -> bool:
        result = api(f"advisor/students/{student}/risk", "advisor", course_id=COURSE)
        alerts = api("advisor/alerts", "advisor", course_id=COURSE, limit=100)
        matching = [row for row in alerts.get("items", []) if row["student_id"] == student]
        return bool(
            any(row["score"] == expected for row in result.get("courses", []))
            and len(matching) == 1
            and matching[0]["status"] == ("RESOLVED" if recover else "NEW")
        )

    wait(visible, "Expected Advisor risk/alert result was not visible")
    return {"elapsed_ms": (time.perf_counter() - started) * 1000, "score": expected}


def setup_risk(at: datetime) -> None:
    with connect() as conn:
        upsert(
            conn,
            "courses",
            {
                "id": COURSE,
                "title": "Engine benchmark",
                "created_at": at - 40 * DAY,
                "telemetry_enabled": True,
            },
        )
        upsert(
            conn,
            "assignments",
            {
                "id": ASSIGNMENT,
                "course_id": COURSE,
                "title": "Due lab",
                "required": True,
                "published_at": at - 30 * DAY,
                "deadline": at - 2 * DAY,
            },
        )
        upsert(conn, "clocks", {"id": "engine-bench-clock", "evaluated_at": at})

    def ready() -> bool:
        with connect() as conn:
            return bool(
                conn.execute(
                    "SELECT 1 FROM analytics.clean_rows "
                    "WHERE table_name='assignments' AND row_key=%s",
                    (ASSIGNMENT,),
                ).fetchone()
            ) and bool(state(conn, "evaluation_clock"))

    wait(ready, "Risk fixture metadata did not arrive through CDC")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", choices=("spark", "flink"))
    parser.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--e2e-repeats", type=int, default=5)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--restore-only", action="store_true")
    args = parser.parse_args()
    require_isolation()
    with connect() as conn:
        current = state(conn, "evaluation_clock")
    at = (
        timestamp(current)
        if current
        else datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    )
    observer = Observer(args.engine, args.run_id, at)
    journal = Journal(args.output, "BR5", args.engine, args.run_id)
    journal.meta.update(
        {
            "engine_version": "3.5.1" if args.engine == "spark" else "1.19.3",
            "cpu_limit": 2,
            "memory_limit_gib": 2,
            "publish_interval_seconds": 5,
            "flink_checkpoint_seconds": 10 if args.engine == "flink" else None,
            "window_hours": 168,
            "window_slide_hours": 1,
            "allowed_lateness_days": 21,
        }
    )
    try:
        if args.restore_only:
            original = json.loads(args.output.read_text())
            journal.rows.extend(original.pop("trials"))
            journal.meta.update(original)
            journal.trial("restart", 0, 1, lambda: restart_parity(observer, args.run_id))
            return
        if not journal.trial("correctness", 0, 1, lambda: correctness(observer, args.run_id)):
            return
        for size in args.sizes:
            for repetition in range(args.repeats + 1):
                rows = workload(f"{args.run_id}-{size}-{repetition}", size, at)

                def operation(
                    rows: list[dict[str, Any]] = rows,
                    size: int = size,
                ) -> dict[str, Any]:
                    expected = windows(rows, list(observer.ends))
                    started = time.perf_counter()
                    offsets = observer.send(rows)
                    wait(lambda: observer.confirmed(expected, offsets), "Stream parity timed out")
                    elapsed = time.perf_counter() - started
                    return {
                        "elapsed_ms": elapsed * 1000,
                        "events_per_second": size / elapsed,
                        "input_messages": len(rows),
                    }

                phase = "warmup" if repetition == 0 else "processing"
                journal.trial(phase, size, repetition, operation)
        if args.e2e_repeats:
            setup_risk(at)
        for repetition in range(1, args.e2e_repeats + 1):
            student = f"{args.run_id}-e2e-{repetition}"
            if journal.trial(
                "e2e_alert",
                4,
                repetition,
                partial(risk_scenario, observer, student, False),
            ):
                journal.trial(
                    "e2e_recovery",
                    4,
                    repetition,
                    partial(risk_scenario, observer, student, True),
                )
    finally:
        observer.close()


if __name__ == "__main__":
    main()
