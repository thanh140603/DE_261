"""Publish synthetic LMS/telemetry events to Kafka for the BR1/BR3 services.

Kept intentionally small and dependency-light (argparse + the shared publisher).
Run with ``PYTHONPATH=src python -m edu_platform.demo.publish --help``.
"""

from __future__ import annotations

import argparse
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from edu_platform.demo import seed
from edu_platform.platform.messaging.kafka_producer import KafkaEventPublisher
from edu_platform.platform.messaging.topics import Topic
from edu_platform.shared_kernel.domain.ids import new_id


def _course(course_id: str) -> seed.Course:
    try:
        return seed.course(course_id)
    except StopIteration:
        raise SystemExit(f"unknown course {course_id!r}") from None


def _assignment(course_id: str) -> seed.Assignment:
    for assignment in seed.ASSIGNMENTS:
        if assignment.course_id == course_id:
            return assignment
    raise SystemExit(f"no assignment for course {course_id!r}")


def lms_deadline(course_id: str, hours: int) -> tuple[str, dict[str, Any]]:
    course = _course(course_id)
    assignment = _assignment(course_id)
    payload = {
        "event_id": new_id(),
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "course_id": course.id,
        "course_title": course.title,
        "assignment_id": assignment.id,
        "title": assignment.title,
        "hours_to_deadline": hours,
    }
    return Topic.DEADLINE_APPROACHING.value, payload


def lms_assignment_created(course_id: str) -> tuple[str, dict[str, Any]]:
    course = _course(course_id)
    assignment = _assignment(course_id)
    payload = {
        "event_id": new_id(),
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "course_id": course.id,
        "course_title": course.title,
        "assignment_id": assignment.id,
        "title": assignment.title,
        "due_at": (datetime.now(tz=UTC) + timedelta(days=3)).isoformat(),
    }
    return Topic.ASSIGNMENT_CREATED.value, payload


def lms_course_updated(course_id: str, content_id: str | None) -> tuple[str, dict[str, Any]]:
    course = _course(course_id)
    content = content_id or (course.lessons[0].content_id if course.lessons else "content")
    payload = {
        "event_id": new_id(),
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "course_id": course.id,
        "course_title": course.title,
        "content_id": content,
        "change_summary": f"{course.title} was updated.",
    }
    return Topic.COURSE_UPDATED.value, payload


def telemetry(count: int, learner_id: str) -> list[tuple[str, dict[str, Any]]]:
    learner = seed.learner(learner_id)
    course = seed.course(random.choice(learner.course_ids))
    lesson = random.choice(course.lessons)
    out: list[tuple[str, dict[str, Any]]] = []
    for _ in range(count):
        verb = random.choice(["viewed", "played", "completed", "attempted"])
        out.append(
            (
                Topic.TELEMETRY_RAW.value,
                {
                    "event_id": new_id(),
                    "schema_version": "1.1",
                    "learner_id": learner.id,
                    "course_id": course.id,
                    "content_id": lesson.content_id,
                    "session_id": f"{learner.id}-demo",
                    "verb": verb,
                    "platform": "web",
                    "occurred_at": datetime.now(tz=UTC).isoformat(),
                },
            )
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish demo events to Kafka.")
    parser.add_argument("--bootstrap", default="localhost:9092")
    sub = parser.add_subparsers(dest="kind", required=True)

    lms = sub.add_parser("lms")
    lms.add_argument(
        "--event",
        choices=["deadline_approaching", "assignment_created", "course_updated"],
        required=True,
    )
    lms.add_argument("--course", required=True)
    lms.add_argument("--hours", type=int, default=6)
    lms.add_argument("--content")

    tel = sub.add_parser("telemetry")
    tel.add_argument("--count", type=int, default=10)
    tel.add_argument("--learner", default="l-002")

    args = parser.parse_args()
    publisher = KafkaEventPublisher(args.bootstrap, client_id="edu-demo-publish")

    if args.kind == "lms":
        if args.event == "deadline_approaching":
            topic, payload = lms_deadline(args.course, args.hours)
        elif args.event == "assignment_created":
            topic, payload = lms_assignment_created(args.course)
        else:
            topic, payload = lms_course_updated(args.course, args.content)
        publisher.publish_raw(topic, key=payload["event_id"], payload=payload)
        print(f"published {topic}")
    else:
        for topic, payload in telemetry(args.count, args.learner):
            publisher.publish_raw(topic, key=payload["learner_id"], payload=payload)
        print(f"published {args.count} telemetry events")

    publisher.close()


if __name__ == "__main__":
    main()
