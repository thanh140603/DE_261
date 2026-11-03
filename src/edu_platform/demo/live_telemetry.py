"""Synthetic *live* telemetry (current timestamps) for the BR6/BR7/BR8 streaming path.

Each generated session watches one lesson video of an enrolled course: plays from the
start, pauses and rewinds around a hotspot at ~40 % of the video (the confusing moment the
heatmap should reveal), and may log in, complete, attempt or post (BR8 engagement).
Data-quality cases mirror the bronze seed: legacy schema 1.0 payloads, an unknown verb
(-> DLQ), a leaked email (dropped by PiiPolicy), a few late mobile events and a few
devices whose clock runs ahead (pinned to ingestion time by ClockSkewPolicy).
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from edu_platform.demo import seed

HOTSPOT = 0.4


def session_events(rng: random.Random, now: datetime) -> list[dict[str, Any]]:
    learner = rng.choice([lr for lr in seed.LEARNERS if lr.course_ids])
    course = seed.course(rng.choice(learner.course_ids))
    lesson = rng.choice(course.lessons)
    platform = rng.choice(("web", "web", "android", "ios"))
    session = f"{rng.getrandbits(48):012x}"
    hotspot = int(lesson.duration_sec * HOTSPOT)
    plan: list[tuple[str, int | None]] = [("logged_in", None), ("played", 0)]
    for _ in range(rng.randint(1, 3)):  # confusion: pause, rewind a little, play again
        stop = max(0, hotspot + rng.randint(-8, 8))
        plan += [("paused", stop), ("seeked", max(0, stop - rng.randint(5, 25))), ("played", stop)]
    if rng.random() < 0.5:
        plan.append(("completed", None))
    plan += [(v, None) for v in ("attempted", "posted") if rng.random() < 0.3]
    # the session has just ended: timestamps run up to `now`, never past it (a client clock
    # ahead of the server is a data-quality case of its own, see ClockSkewPolicy)
    gaps = [rng.randint(2, 30) for _ in plan]
    at = now - timedelta(seconds=sum(gaps) + rng.randint(0, 30))
    events = []
    for (verb, position), gap in zip(plan, gaps, strict=True):
        at += timedelta(seconds=gap)
        content = lesson.content_id if position is not None or verb == "completed" else None
        events.append(
            _payload(rng, learner.id, course.id, content, session, verb, platform, at, position)
        )
    return events


def _payload(
    rng: random.Random, learner_id: str, course_id: str, content_id: str | None, session: str,
    verb: str, platform: str, at: datetime, position: int | None,
) -> dict[str, Any]:  # fmt: skip
    payload: dict[str, Any] = {
        "event_id": str(uuid.UUID(int=rng.getrandbits(128))),
        "schema_version": "1.1",
        "learner_id": learner_id,
        "course_id": course_id,
        "content_id": content_id,
        "session_id": session,
        "verb": verb,
        "platform": platform,
        "occurred_at": at.isoformat(),
        "video_position_sec": position,
        "email": f"{learner_id}@example.edu",  # client leak; PiiPolicy drops it
    }
    r = rng.random()
    if r < 0.05:  # legacy client
        payload["schema_version"] = "1.0"
        payload["ts"] = payload.pop("occurred_at")
        payload.pop("platform")
    elif r < 0.07:  # malformed
        payload["verb"] = "teleported"
    elif r < 0.09 and platform != "web":  # offline mobile replay: older than the watermark
        payload["occurred_at"] = (at - timedelta(minutes=rng.randint(10, 90))).isoformat()
    elif r < 0.10 and platform != "web":  # device clock 10 min ahead (ClockSkewPolicy)
        payload["occurred_at"] = (at + timedelta(minutes=10)).isoformat()
    return payload


def generate(
    sessions: int, *, seed_value: int | None = None, now: datetime | None = None
) -> list[dict[str, Any]]:
    rng = random.Random(seed_value)
    now = now or datetime.now(tz=UTC)
    return [e for _ in range(sessions) for e in session_events(rng, now)]
