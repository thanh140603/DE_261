"""Synthetic bronze data for exercising the warehouse without Kafka/Debezium.

Writes rows exactly as the landing job would (bronze.telemetry_raw / cdc_events /
domain_events), built from the demo reference data (demo/seed.py) plus synthetic Acme
learners so the BR thresholds (30 attempts, k = 5) are reachable. Scenarios baked in:

- BR4  a-py-even test t5_pairs has a wrong expected value -> always fails (anomalous)
- BR5  l-004 disengages; risk score climbs past 0.7 -> alert -> drops c-py-201 later
- BR6  org-globex has fewer than 5 learners per course -> suppressed in mart.org_progress
- BR7  v-sql-joins is re-cut (version 2, shorter) 10 days before the end; rewind hotspot
- BR8  l-004 engagement declines week over week
- data quality: late mobile events, client re-sends (duplicates), schema 1.0 payloads,
  malformed events (DLQ), a learner whose CDC row arrives after their first events
  (late-arriving dimension), an advisor change (SCD2 version).

  edu warehouse seed-bronze --end-date 2026-10-17 --days 35 [--reset]
"""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import typer

from edu_platform.demo import seed
from edu_platform.platform.batch.spark_session import build_spark
from edu_platform.platform.config import get_settings

TELEMETRY_TOPIC = "telemetry.events.raw.v1"
BROKEN_TEST = ("a-py-even", "t5_pairs")
AT_RISK = "l-004"
LATE_LEARNER = "l-131"
RECUT_CONTENT = ("v-sql-joins", 390)
ASSIGNMENT_DUE_OFFSET = {"a-py-fizz": 14, "a-sql-joins": 18, "a-py-even": 24}


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class Learner:
    id: str
    org_id: str
    advisor_id: str
    course_ids: tuple[str, ...]
    skill: float
    platform_weights: tuple[float, float, float]
    name: str = ""


@dataclass
class Bronze:
    """Accumulates bronze rows with monotonically increasing LSNs and offsets."""

    telemetry: list[tuple[Any, ...]] = field(default_factory=list)
    cdc: list[tuple[Any, ...]] = field(default_factory=list)
    events: list[tuple[Any, ...]] = field(default_factory=list)
    lsn: int = 1_000_000
    offsets: dict[str, int] = field(default_factory=dict)

    def _offset(self, topic: str) -> int:
        self.offsets[topic] = self.offsets.get(topic, -1) + 1
        return self.offsets[topic]

    def cdc_row(self, table: str, op: str, at: datetime, row: dict[str, Any], key: str) -> None:
        self.lsn += 17
        after = {**row, "__deleted": "true" if op == "d" else "false"}
        self.cdc.append(
            (
                table,
                op,
                self.lsn,
                self.lsn // 10,
                at.replace(tzinfo=None),
                json.dumps({key: row[key]}),
                json.dumps(after, default=str),
                0,
                self._offset(f"cdc.{table}"),
                at.date(),
                datetime.now(tz=UTC).replace(tzinfo=None),
            )
        )

    def event(self, topic: str, at: datetime, payload: dict[str, Any], key: str) -> None:
        self.events.append(
            (
                topic,
                payload.get("event_id"),
                key,
                json.dumps(payload, default=str),
                0,
                self._offset(topic),
                at.replace(tzinfo=None),
                at.date(),
                datetime.now(tz=UTC).replace(tzinfo=None),
            )
        )

    def telemetry_row(self, payload: dict[str, Any], received_at: datetime) -> None:
        self.telemetry.append(
            (
                payload.get("event_id"),
                payload.get("learner_id"),
                payload.get("schema_version"),
                json.dumps(payload),
                TELEMETRY_TOPIC,
                sum(map(ord, str(payload.get("learner_id")))) % 24,  # key = learner_id
                self._offset(TELEMETRY_TOPIC),
                received_at.replace(tzinfo=None),
                received_at.date(),
                datetime.now(tz=UTC).replace(tzinfo=None),
            )
        )


class Generator:
    def __init__(self, end_date: date, days: int, rng_seed: int = 261) -> None:
        self.rng = random.Random(rng_seed)
        self.end = datetime.combine(end_date, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
        self.start = self.end - timedelta(days=days)
        self.days = days
        self.out = Bronze()
        self.learners = self._learners()
        self.courses = {c.id: c for c in seed.COURSES}
        self.content_duration = {
            ls.content_id: ls.duration_sec for c in seed.COURSES for ls in c.lessons
        }
        self.progress: dict[tuple[str, str], int] = {}  # (learner, course) -> lessons completed
        self.attempts: dict[tuple[str, str], int] = {}  # (learner, assignment) -> submissions
        self.enrollment_ids: dict[tuple[str, str], str] = {}
        self.risk_alerted: set[tuple[str, str]] = set()

    # --- reference data -------------------------------------------------------------
    def _learners(self) -> list[Learner]:
        rng = self.rng
        out = [
            Learner(
                lr.id,
                lr.org_id,
                lr.advisor_id,
                lr.course_ids,
                0.45 if lr.id == AT_RISK else rng.uniform(0.6, 0.95),
                (0.6, 0.25, 0.15),
                lr.name,
            )
            for lr in seed.LEARNERS
        ]
        for i in range(101, 132):
            courses = ("c-sql-101", "c-py-201") + (("c-de-301",) if i % 3 == 0 else ())
            out.append(
                Learner(
                    f"l-{i}",
                    "org-acme",
                    "adv-1" if i % 2 else "adv-2",
                    courses,
                    rng.uniform(0.55, 0.95),
                    rng.choice([(0.8, 0.1, 0.1), (0.3, 0.5, 0.2), (0.4, 0.2, 0.4)]),
                    f"Synthetic Learner {i}",
                )
            )
        return out

    def reference(self) -> None:
        t0 = self.start - timedelta(days=30)
        for org in seed.ORGANISATIONS:
            plan = "enterprise" if org.id == "org-acme" else "team"
            row = {
                "organisation_id": org.id,
                "name": org.name,
                "plan": plan,
                "updated_at": _iso(t0),
            }
            self.out.cdc_row("organisations", "r", t0, row, "organisation_id")
        for c in seed.COURSES:
            self.out.cdc_row(
                "courses",
                "r",
                t0,
                {
                    "course_id": c.id,
                    "title": c.title,
                    "skill": c.skill,
                    "level": "beginner" if c.id.endswith("101") else "intermediate",
                    "owner_organisation_id": c.org_id,
                    "updated_at": _iso(t0),
                },
                "course_id",
            )
            for ls in c.lessons:
                self.out.cdc_row(
                    "lessons",
                    "r",
                    t0,
                    {
                        "lesson_id": ls.id,
                        "course_id": c.id,
                        "content_id": ls.content_id,
                        "title": ls.title,
                        "ordinal": ls.ordinal,
                        "updated_at": _iso(t0),
                    },
                    "lesson_id",
                )
                self._content_version(ls.content_id, c.id, ls.title, 1, ls.duration_sec, t0)
        for a in seed.ASSIGNMENTS:
            due = self.start + timedelta(days=ASSIGNMENT_DUE_OFFSET[a.id])
            self.out.cdc_row(
                "assignments",
                "r",
                t0,
                {
                    "assignment_id": a.id,
                    "course_id": a.course_id,
                    "lesson_id": None,
                    "title": a.title,
                    "language": a.language,
                    "due_at": _iso(due),
                    "max_score": 100.0,
                    "updated_at": _iso(t0),
                },
                "assignment_id",
            )
            for i, t in enumerate(a.tests):
                self.out.cdc_row(
                    "test_cases",
                    "r",
                    t0,
                    {
                        "assignment_id": a.id,
                        "test_case_id": t.id,
                        "name": t.id.split("_", 1)[1].replace("_", " "),
                        "weight": 1.0,
                        "is_hidden": i >= 3,
                        "updated_at": _iso(t0),
                    },
                    "test_case_id",
                )
        for lr in self.learners:
            first_seen = t0 if lr.id != LATE_LEARNER else self.end - timedelta(days=3)
            if lr.id != LATE_LEARNER:
                self._learner_row(lr, "r", first_seen)
            for cid in lr.course_ids:
                eid = str(uuid.UUID(int=self.rng.getrandbits(128)))
                self.enrollment_ids[(lr.id, cid)] = eid
                self._enrollment(
                    lr, cid, "active", first_seen, "r" if lr.id != LATE_LEARNER else "c"
                )
        late = next(lr for lr in self.learners if lr.id == LATE_LEARNER)
        self._learner_row(late, "c", self.end - timedelta(days=3))

    def _learner_row(self, lr: Learner, op: str, at: datetime) -> None:
        slug = lr.id.replace("-", "")
        self.out.cdc_row(
            "learners",
            op,
            at,
            {
                "learner_id": lr.id,
                "organisation_id": lr.org_id,
                "advisor_id": lr.advisor_id,
                "email": f"{slug}@example.edu",  # dropped before silver
                "full_name": lr.name or f"Learner {slug}",  # dropped before silver
                "country_code": "VN",
                "signed_up_at": _iso(self.start - timedelta(days=40)),
                "updated_at": _iso(at),
            },
            "learner_id",
        )

    def _enrollment(self, lr: Learner, course_id: str, status: str, at: datetime, op: str) -> None:
        self.out.cdc_row(
            "enrollments",
            op,
            at,
            {
                "enrollment_id": self.enrollment_ids[(lr.id, course_id)],
                "learner_id": lr.id,
                "course_id": course_id,
                "organisation_id": lr.org_id,
                "status": status,
                "enrolled_at": _iso(self.start - timedelta(days=20)),
                "updated_at": _iso(at),
            },
            "enrollment_id",
        )

    def _content_version(
        self, content_id: str, course_id: str, title: str, version: int, duration: int, at: datetime
    ) -> None:
        op = "r" if version == 1 else "u"
        self.out.cdc_row(
            "course_content",
            op,
            at,
            {
                "content_id": content_id,
                "course_id": course_id,
                "content_type": "video_transcript",
                "title": title,
                "version": version,
                "object_key": f"courses/{course_id}/{content_id}/v{version}.vtt",
                "duration_sec": duration,
                "updated_at": _iso(at),
            },
            "content_id",
        )
        published = {
            "event_id": str(uuid.UUID(int=self.rng.getrandbits(128))),
            "event_type": "content.version_published.v1",
            "aggregate_id": content_id,
            "occurred_at": _iso(at),
            "course_id": course_id,
            "version": version,
        }
        self.out.event("content.updated.v1", at, published, content_id)
        indexed_at = at + timedelta(seconds=self.rng.randint(40, 240))
        indexed = {
            "event_id": str(uuid.UUID(int=self.rng.getrandbits(128))),
            "event_type": "content.indexed.v1",
            "aggregate_id": content_id,
            "occurred_at": _iso(indexed_at),
            "version": version,
            "chunk_count": self.rng.randint(8, 20),
        }
        self.out.event("content.indexed.v1", indexed_at, indexed, content_id)

    # --- activity -------------------------------------------------------------------
    def activity(self) -> None:
        recut_day = self.end - timedelta(days=10)
        recut_done = False
        advisor_change = self.end - timedelta(days=12)
        for d in range(self.days):
            day = self.start + timedelta(days=d)
            if not recut_done and day >= recut_day:
                cid, duration = RECUT_CONTENT
                self.content_duration[cid] = duration
                self._content_version(
                    cid, "c-sql-101", "Joins (re-recorded)", 2, duration, day + timedelta(hours=7)
                )
                recut_done = True
            if day.date() == advisor_change.date():
                lr = next(x for x in self.learners if x.id == "l-003")
                lr.advisor_id = "adv-2"
                self._learner_row(lr, "u", day + timedelta(hours=9))
            for lr in self.learners:
                if lr.id == LATE_LEARNER and day < self.end - timedelta(days=5):
                    continue
                for course_id in lr.course_ids:
                    if self._is_active(lr, d, day):
                        self._session(lr, course_id, day)
                    self._risk(lr, course_id, d, day)
            self._deadline_reminders(day)

    def _is_active(self, lr: Learner, d: int, day: datetime) -> bool:
        if lr.id == AT_RISK:
            p = [0.9, 0.8, 0.45, 0.15, 0.03, 0.0][min(d // 7, 5)]
        else:
            p = 0.5 if day.weekday() < 5 else 0.25
        return self.rng.random() < p

    def _session(self, lr: Learner, course_id: str, day: datetime) -> None:
        rng = self.rng
        course = self.courses[course_id]
        ts = day + timedelta(hours=rng.randint(7, 21), minutes=rng.randint(0, 59))
        session = str(uuid.UUID(int=rng.getrandbits(128)))
        platform = rng.choices(("web", "android", "ios"), weights=lr.platform_weights)[0]
        self._emit(lr, course_id, None, session, "logged_in", platform, ts)
        pointer = self.progress.get((lr.id, course_id), 0)
        lesson = course.lessons[min(pointer, len(course.lessons) - 1)]
        ts += timedelta(minutes=1)
        self._emit(lr, course_id, lesson.content_id, session, "viewed", platform, ts)
        duration = self.content_duration[lesson.content_id]
        pos = 0
        self._emit(lr, course_id, lesson.content_id, session, "played", platform, ts, pos)
        for _ in range(rng.randint(2, 7)):
            pos = min(duration + 5, pos + rng.randint(20, 120))
            ts += timedelta(seconds=rng.randint(20, 120))
            if lesson.content_id == RECUT_CONTENT[0] and 150 <= pos <= 260 and rng.random() < 0.8:
                back = max(0, pos - rng.randint(30, 60))  # rewind hotspot (hard section)
                self._emit(lr, course_id, lesson.content_id, session, "seeked", platform, ts, back)
                pos = back
            verb = rng.choice(("paused", "played", "seeked"))
            self._emit(lr, course_id, lesson.content_id, session, verb, platform, ts, pos)
        if pointer < len(course.lessons) and rng.random() < lr.skill * 0.2:
            ts += timedelta(minutes=2)
            self._emit(lr, course_id, lesson.content_id, session, "completed", platform, ts)
            self._lesson_progress(lr, course_id, lesson.id, 100, ts)
            self.progress[(lr.id, course_id)] = pointer + 1
            if pointer + 1 == len(course.lessons):
                self._enrollment(lr, course_id, "completed", ts + timedelta(minutes=5), "u")
        elif pointer < len(course.lessons):
            self._lesson_progress(lr, course_id, lesson.id, rng.choice((25, 50, 75)), ts)
        if rng.random() < 0.15:
            self._emit(lr, course_id, None, session, "posted", platform, ts + timedelta(minutes=3))
        for a in (a for a in seed.ASSIGNMENTS if a.course_id == course_id):
            due_day = ASSIGNMENT_DUE_OFFSET[a.id]
            day_idx = (day - self.start).days
            if due_day - 9 <= day_idx <= due_day + 2 and rng.random() < 0.35:
                self._submit(lr, a, ts + timedelta(minutes=10), session, platform)

    def _emit(
        self,
        lr: Learner,
        course_id: str,
        content_id: str | None,
        session: str,
        verb: str,
        platform: str,
        at: datetime,
        position: int | None = None,
    ) -> None:
        rng = self.rng
        payload: dict[str, Any] = {
            "event_id": str(uuid.UUID(int=rng.getrandbits(128))),
            "schema_version": "1.1",
            "learner_id": lr.id,
            "course_id": course_id,
            "content_id": content_id,
            "session_id": session,
            "verb": verb,
            "platform": platform,
            "occurred_at": _iso(at),
            "video_position_sec": position,
            "extensions": {"app_version": "4.2.0"},
        }
        received = at + timedelta(seconds=rng.randint(1, 20))
        r = rng.random()
        if platform != "web" and r < 0.04:  # offline mobile client syncs days later
            received = at + timedelta(days=rng.randint(1, 3), hours=rng.randint(0, 5))
        elif r < 0.09:  # legacy 1.0 client: 'ts' instead of occurred_at, no platform
            payload["schema_version"] = "1.0"
            payload["ts"] = payload.pop("occurred_at")
            payload.pop("platform")
        elif r < 0.10:  # malformed: unknown verb -> DLQ
            payload["verb"] = "teleported"
        if received >= self.end:
            return
        payload["email"] = f"{lr.id}@example.edu"  # client leak; PiiPolicy drops it
        self.out.telemetry_row(payload, received)
        if rng.random() < 0.02:  # client re-send of the same event
            self.out.telemetry_row(
                payload, min(received + timedelta(minutes=30), self.end - timedelta(seconds=1))
            )

    def _lesson_progress(
        self, lr: Learner, course_id: str, lesson_id: str, pct: int, at: datetime
    ) -> None:
        self.out.cdc_row(
            "lesson_progress",
            "u",
            at,
            {
                "learner_id": lr.id,
                "lesson_id": lesson_id,
                "course_id": course_id,
                "percent_done": pct,
                "updated_at": _iso(at),
            },
            "lesson_id",
        )

    def _submit(
        self, lr: Learner, a: seed.Assignment, at: datetime, session: str, platform: str
    ) -> None:
        rng = self.rng
        attempt = self.attempts.get((lr.id, a.id), 0) + 1
        self.attempts[(lr.id, a.id)] = attempt
        sid = str(uuid.UUID(int=rng.getrandbits(128)))
        self._emit(lr, a.course_id, None, session, "submitted", platform, at)
        row = {
            "submission_id": sid,
            "learner_id": lr.id,
            "assignment_id": a.id,
            "attempt_number": attempt,
            "language": a.language,
            "code_ref": f"submissions/{a.id}/{sid}.src",
            "status": "queued",
            "submitted_at": _iso(at),
            "updated_at": _iso(at),
        }
        self.out.cdc_row("submissions", "c", at, row, "submission_id")
        graded_at = at + timedelta(seconds=rng.randint(3, 40))
        assertions = []
        for t in a.tests:
            if (a.id, t.id) == BROKEN_TEST:
                status = "failed"
            else:
                p = min(0.98, lr.skill + 0.08 * (attempt - 1) - (0.2 if t.id == "t3_ties" else 0))
                status = "passed" if rng.random() < p else rng.choice(("failed", "failed", "error"))
            assertions.append(
                {
                    "test_case_id": t.id,
                    "status": status,
                    "expected": t.expected,
                    "actual": t.expected if status == "passed" else "None",
                    "duration_ms": rng.randint(2, 90),
                }
            )
        passed = sum(1 for x in assertions if x["status"] == "passed")
        result = {
            "submission_id": sid,
            "worker_run_id": str(uuid.UUID(int=rng.getrandbits(128))),
            "stdout": "",
            "stderr": "" if passed == len(assertions) else "AssertionError",
            "exit_code": 0 if passed == len(assertions) else 1,
            "exec_time_ms": rng.randint(40, 900),
            "max_rss_kb": rng.randint(9000, 60000),
            "timed_out": False,
            "assertions": assertions,
        }
        self.out.event("grading.sandbox_result.raw.v1", graded_at, result, sid)
        self.out.cdc_row(
            "submissions",
            "u",
            graded_at,
            {**row, "status": "graded", "updated_at": _iso(graded_at)},
            "submission_id",
        )
        pass_rate = round(passed / len(assertions), 4)
        self.out.cdc_row(
            "grades",
            "c",
            graded_at,
            {
                "submission_id": sid,
                "score": round(100 * pass_rate, 2),
                "pass_rate": pass_rate,
                "graded_at": _iso(graded_at),
            },
            "submission_id",
        )

    def _risk(self, lr: Learner, course_id: str, d: int, day: datetime) -> None:
        rng = self.rng
        if lr.id == LATE_LEARNER and day < self.end - timedelta(days=5):
            return
        if lr.id == AT_RISK and course_id == "c-py-201":
            score = min(0.95, 0.2 + max(0, d - 10) * 0.035)
        elif rng.random() < 0.6:
            score = round(rng.uniform(0.05, 0.4) * (1.2 - lr.skill), 3)
        else:
            return
        at = day + timedelta(hours=23, minutes=rng.randint(0, 50))
        self.out.event(
            "risk.learner_score.v1",
            at,
            {
                "event_id": str(uuid.UUID(int=rng.getrandbits(128))),
                "learner_id": lr.id,
                "course_id": course_id,
                "score": round(score, 3),
                "computed_at": _iso(at),
            },
            f"{lr.id}:{course_id}",
        )
        key = (lr.id, course_id)
        if score >= 0.7 and key not in self.risk_alerted:
            self.risk_alerted.add(key)
            self.out.event(
                "risk.dropout_alert.v1",
                at,
                {
                    "event_id": str(uuid.UUID(int=rng.getrandbits(128))),
                    "event_type": "risk.dropout_risk_detected.v1",
                    "aggregate_id": f"{lr.id}:{course_id}",
                    "occurred_at": _iso(at),
                    "learner_id": lr.id,
                    "course_id": course_id,
                    "score": round(score, 3),
                    "top_signals": ["login_gap", "grade_declining", "progress_stalled"],
                },
                f"{lr.id}:{course_id}",
            )
            drop_at = at + timedelta(days=6)
            if drop_at < self.end:
                self._enrollment(lr, course_id, "dropped", drop_at, "u")

    def _deadline_reminders(self, day: datetime) -> None:
        rng = self.rng
        for a in seed.ASSIGNMENTS:
            if (day - self.start).days != ASSIGNMENT_DUE_OFFSET[a.id] - 2:
                continue
            for lr in self.learners:
                if a.course_id not in lr.course_ids:
                    continue
                at = day + timedelta(hours=8, seconds=rng.randint(0, 600))
                suppressed = rng.random() < 0.1
                topic = "notification.suppressed.v1" if suppressed else "notification.dispatched.v1"
                payload = {
                    "event_id": str(uuid.UUID(int=rng.getrandbits(128))),
                    "event_type": topic,
                    "aggregate_id": str(uuid.UUID(int=rng.getrandbits(128))),
                    "occurred_at": _iso(at),
                    "recipient_id": lr.id,
                    "channel": None if suppressed else rng.choice(("push", "in_app", "email")),
                    "reason": "rate_limited" if suppressed else None,
                }
                self.out.event(topic, at, payload, lr.id)


def seed_bronze(
    end_date: str = typer.Option(..., help="Last day of generated activity (YYYY-MM-DD)"),
    days: int = typer.Option(35, help="Number of days of history"),
    reset: bool = typer.Option(False, help="Delete existing bronze rows first"),
) -> None:
    """Generate synthetic bronze data (landing format) for warehouse demos and tests."""
    gen = Generator(date.fromisoformat(end_date), days)
    gen.reference()
    gen.activity()
    spark = build_spark("edu-seed-bronze", get_settings())
    targets = {
        "bronze.telemetry_raw": gen.out.telemetry,
        "bronze.cdc_events": gen.out.cdc,
        "bronze.domain_events": gen.out.events,
    }
    for table, rows in targets.items():
        if reset:
            spark.sql(f"DELETE FROM {table}")
        spark.createDataFrame(rows, spark.table(table).schema).writeTo(table).append()
        typer.echo(f"{table}: {len(rows)} rows")
