"""Telemetry simulator, LMS/CDC event emitters and scripted scenarios.

Everything here only *produces* upstream facts (client events, OLTP row
changes, LMS business events). Pipelines react through demo/handlers.py.
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from edu_platform.contexts.grading.application.enqueue_submission import EnqueueSubmissionCommand
from edu_platform.contexts.grading.domain.model import Language, Submission
from edu_platform.demo import seed
from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.handlers import CDC_TOPICS, observe_risk_signals
from edu_platform.platform.messaging.topics import Topic
from edu_platform.shared_kernel.domain.ids import new_id

VERB_WEIGHTS = {
    "viewed": 28,
    "played": 28,
    "paused": 10,
    "seeked": 10,
    "attempted": 10,
    "completed": 5,
    "logged_in": 5,
    "posted": 4,
}
HOTSPOTS = {"v-sql-joins": (170, 230), "v-py-lists": (90, 140), "v-de-medallion": (300, 360)}
CORRECT_SUM_EVEN = "def sum_even(nums):\n    return sum(n for n in nums if n % 2 == 0)\n"


class Simulator:
    def __init__(self, p: DemoPlatform, rng_seed: int = 42) -> None:
        self.p = p
        self.rng = random.Random(rng_seed)
        self.running = False
        self.rate_per_sec = 3.0
        self.generated = 0
        self._task: asyncio.Task[None] | None = None

    # --- single events ----------------------------------------------------------
    def make_payload(
        self,
        learner: seed.Learner | None = None,
        verb: str | None = None,
        occurred_at: datetime | None = None,
        course_id: str | None = None,
        content_id: str | None = None,
        video_position_sec: int | None = None,
        platform: str | None = None,
        schema_version: str = "1.1",
    ) -> dict[str, Any]:
        learner = learner or self.rng.choice(seed.LEARNERS)
        course = (
            seed.course(course_id)
            if course_id
            else seed.course(self.rng.choice(learner.course_ids))
        )
        lesson = None
        if content_id:
            found = seed.lesson_by_content(content_id)
            lesson = found[1] if found else None
        lesson = lesson or self.rng.choice(course.lessons)
        verb = verb or self.rng.choices(list(VERB_WEIGHTS), weights=list(VERB_WEIGHTS.values()))[0]
        occurred_at = occurred_at or datetime.now(tz=UTC)
        if video_position_sec is None and verb in {"played", "paused", "seeked"}:
            lo, hi = HOTSPOTS.get(lesson.content_id, (0, lesson.duration_sec))
            if verb == "seeked" and self.rng.random() < 0.7:
                video_position_sec = self.rng.randint(lo, hi)
            else:
                video_position_sec = self.rng.randint(0, lesson.duration_sec - 1)
        payload: dict[str, Any] = {
            "event_id": new_id(),
            "schema_version": schema_version,
            "learner_id": learner.id,
            "course_id": course.id,
            "content_id": lesson.content_id if verb != "logged_in" else None,
            "session_id": f"{learner.id}-{occurred_at:%Y%m%d%H}",
            "verb": verb,
            "platform": platform or self.rng.choice(["web", "web", "android", "ios"]),
            "occurred_at": occurred_at.isoformat(),
            "video_position_sec": video_position_sec,
        }
        if schema_version == "1.0":  # old clients: ``ts`` instead of occurred_at, no platform
            payload["ts"] = payload.pop("occurred_at")
            payload.pop("platform")
        return payload

    def ingest(self, payload: dict[str, Any], received_at: datetime | None = None) -> str:
        """Client -> Kafka. Returns the event id; outcome is visible in silver / DLQ."""
        self.generated += 1
        event_id = str(payload.get("event_id") or new_id())
        payload.setdefault("event_id", event_id)
        self.p.bus.emit(
            Topic.TELEMETRY_RAW,
            key=event_id,
            event_type="telemetry.raw",
            payload=payload,
            at=received_at,
        )
        return event_id

    def outcome(self, event_id: str) -> tuple[str, str | None]:
        if event_id in self.p.silver.events:
            return "silver", None
        for d in reversed(self.p.dlq.rows):
            if d.raw.event_id == event_id:
                return "dlq", d.reason
        return "duplicate", "event_id already in silver"

    def generate(self, count: int, *, learner: seed.Learner | None = None) -> dict[str, int]:
        before_silver, before_dlq = len(self.p.silver.events), len(self.p.dlq.rows)
        for _ in range(count):
            picked = (
                learner
                or self.rng.choices(
                    seed.LEARNERS, weights=[1 if it.id == "l-004" else 6 for it in seed.LEARNERS]
                )[0]
            )
            r = self.rng.random()
            occurred_at = datetime.now(tz=UTC)
            schema = "1.0" if r < 0.08 else "1.1"
            if r > 0.95:  # offline mobile replay: arrives late
                occurred_at -= timedelta(seconds=self.rng.randint(400, 1500))
            payload = self.make_payload(picked, occurred_at=occurred_at, schema_version=schema)
            if 0.08 <= r < 0.10:  # broken client build
                payload["verb"] = "scrolled"
            self.ingest(payload)
        return {
            "generated": count,
            "silver": len(self.p.silver.events) - before_silver,
            "dlq": len(self.p.dlq.rows) - before_dlq,
        }

    # --- continuous mode -------------------------------------------------------
    def start(self, rate_per_sec: float | None = None) -> None:
        if rate_per_sec:
            self.rate_per_sec = max(0.2, min(50.0, rate_per_sec))
        if not self.running:
            self.running = True
            self._task = asyncio.get_running_loop().create_task(self._loop())

    def stop(self) -> None:
        self.running = False

    async def _loop(self) -> None:
        carry = 0.0
        while self.running:
            carry += self.rate_per_sec * 0.5
            n, carry = int(carry), carry - int(carry)
            if n:
                await asyncio.to_thread(self.generate, n)
                self.p.broadcaster.publish("stats", self.stats())
            await asyncio.sleep(0.5)

    # --- LMS business events (BR1) -----------------------------------------------
    def emit_lms_event(self, event_type: str, course_id: str, **fields: Any) -> dict[str, Any]:
        topic = {
            "assignment_created": Topic.ASSIGNMENT_CREATED,
            "deadline_approaching": Topic.DEADLINE_APPROACHING,
            "course_updated": Topic.COURSE_UPDATED,
        }[event_type]
        course = seed.course(course_id)
        event_id = new_id()
        payload = {
            "event_id": event_id,
            "occurred_at": datetime.now(tz=UTC).isoformat(),
            "course_id": course.id,
            "course_title": course.title,
            **{k: v for k, v in fields.items() if v is not None},
        }
        payload.setdefault("title", fields.get("title") or f"{course.title} update")
        self.p.last_route_result = {"created": 0, "suppressed": []}
        self.p.bus.emit(topic, key=event_id, event_type=topic.value, payload=payload)
        return {"event_id": event_id, **self.p.last_route_result}

    # --- OLTP row changes (Debezium stand-in) -----------------------------------------
    def emit_cdc(
        self, table: str, learner_id: str, course_id: str, **fields: Any
    ) -> dict[str, Any]:
        row = {
            "__table": table,
            "__op": "u",
            "__ts_ms": int(datetime.now(tz=UTC).timestamp() * 1000),
            "__source_lsn": self.p.bus.counts[CDC_TOPICS[table]] + 1,
            "learner_id": learner_id,
            "course_id": course_id,
            **{k: v for k, v in fields.items() if v is not None},
        }
        self.p.bus.emit(
            CDC_TOPICS[table],
            key=f"{learner_id}:{course_id}",
            event_type=f"cdc.{table}",
            payload=row,
        )
        profile = self.p.risk_repo.get(f"{learner_id}:{course_id}")
        return {
            "learner_id": learner_id,
            "course_id": course_id,
            "score": profile.score.value if profile and profile.score else 0.0,
            "alerted": bool(
                profile
                and profile.last_alert_at
                and profile.score
                and profile.last_alert_at == profile.score.computed_at
            ),
        }

    # --- code submissions --------------------------------------------------------------
    def submit(
        self,
        learner_id: str,
        assignment_id: str,
        code: str,
        synthetic_log: dict[str, Any] | None = None,
    ) -> Submission:
        assignment = seed.assignment(assignment_id)
        self.p.pending_synthetic_log = synthetic_log
        return self.p.enqueue_submission.execute(
            EnqueueSubmissionCommand(
                learner_id=learner_id,
                assignment_id=assignment_id,
                language=Language(assignment.language),
                code=code,
                submitted_at=datetime.now(tz=UTC),
            )
        )

    def synthetic_log(
        self, assignment: seed.Assignment, correct: bool, failing_ids: set[str] | None = None
    ) -> dict[str, Any]:
        failing_ids = failing_ids or set()
        assertions = []
        for t in assignment.tests:
            ok = correct and t.id not in failing_ids
            assertions.append(
                {
                    "test_case_id": t.id,
                    "status": "passed" if ok else "failed",
                    "expected": t.expected,
                    "actual": t.expected if ok else "6" if t.id == "t5_pairs" else "0",
                    "duration_ms": self.rng.randint(1, 9),
                }
            )
        return {
            "worker_run_id": new_id(),
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "exec_time_ms": self.rng.randint(40, 120),
            "max_rss_kb": self.rng.randint(9000, 14000),
            "timed_out": False,
            "assertions": assertions,
        }

    # --- scenarios ---------------------------------------------------------------------
    def scenario(self, name: str) -> dict[str, Any]:
        steps: list[dict[str, str]] = []

        def log(message: str) -> None:
            steps.append({"at": datetime.now(tz=UTC).isoformat(), "message": message})

        if name == "at_risk_learner":
            learner, course = seed.learner("l-004"), seed.course("c-py-201")
            now = datetime.now(tz=UTC)
            log(f"{learner.name} has not logged in for 9 days (telemetry gap).")
            r = observe_risk_signals(
                self.p, learner.id, course.id, self.p.signal_rules.from_login_gap(9, now), now
            )
            log(f"Risk score {r.score:.2f}.")
            log("CDC: lesson_progress row shows 0% on the current lesson (progress stalled).")
            out = self.emit_cdc(
                "lesson_progress", learner.id, course.id, lesson_id="l-py-2", percent_done=0
            )
            log(f"Risk score {out['score']:.2f}.")
            log("CDC: submissions row marked missed for the FizzBuzz deadline.")
            out = self.emit_cdc(
                "submissions", learner.id, course.id, assignment_id="a-py-fizz", status="missed"
            )
            log(f"Risk score {out['score']:.2f}.")
            log("CDC: grades row with score 32 (declining).")
            out = self.emit_cdc(
                "grades", learner.id, course.id, assignment_id="a-py-even", score=32
            )
            log(
                f"Risk score {out['score']:.2f} - {'alert sent to advisor' if out['alerted'] else 'below threshold or in cooldown'}."
            )
            return {"name": name, "steps": steps, "outcome": {**out, "learner_id": learner.id}}

        if name == "broken_test_case":
            assignment = seed.assignment("a-py-even")
            log(
                "12 learners submit a correct sum_even; test t5_pairs expects 7 for [2, 4] (wrong)."
            )
            learners = list(seed.LEARNERS) + list(seed.LEARNERS)[:3]
            for learner in learners:
                self.submit(
                    learner.id,
                    assignment.id,
                    CORRECT_SUM_EVEN,
                    self.synthetic_log(assignment, True, {"t5_pairs"}),
                )
            log("Assessment mart recomputed: t5_pairs pass rate 0% versus assignment median 100%.")
            return {
                "name": name,
                "steps": steps,
                "outcome": {"assignment_id": assignment.id, "item_id": "t5_pairs"},
            }

        if name == "content_update":
            from edu_platform.contexts.content.application.publish_content_version import (
                PublishContentVersionCommand,
            )

            content_id = "v-sql-joins"
            body = (
                "# Joins\n\nAn inner join keeps only rows that match in both tables.\n\n"
                "# Left join\n\nA left join keeps every row from the left table and fills missing matches with NULL.\n\n"
                f"# Updated {datetime.now(tz=UTC):%H:%M:%S}\n\nNew worked example on anti-joins with NOT EXISTS."
            )
            result = self.p.publish_content.execute(
                PublishContentVersionCommand(content_id, body, None, datetime.now(tz=UTC))
            )
            for s in result.steps:
                log(f"{s.step}: {s.status} ({s.ms} ms)")
            out = self.emit_lms_event(
                "course_updated",
                "c-sql-101",
                content_id=content_id,
                change_summary="The Joins transcript gained a section on anti-joins.",
            )
            log(f"course_updated event -> {out['created']} learner notifications.")
            return {
                "name": name,
                "steps": steps,
                "outcome": {"content_id": content_id, "version": result.version, **out},
            }

        if name == "late_mobile_events":
            learner = seed.learner("l-002")
            base = datetime.now(tz=UTC)
            ids = []
            for i in range(8):
                payload = self.make_payload(
                    learner, occurred_at=base - timedelta(seconds=600 + i * 90), platform="android"
                )
                ids.append(self.ingest(payload))
            log("8 Android events replayed 10-20 minutes late (offline queue flushed).")
            for eid in ids[:3]:
                self.ingest({**self.p.bronze.rows[-1].payload, "event_id": eid})
            log("3 of them re-sent by the client (retries) -> deduplicated on event_id.")
            self.ingest(self.make_payload(learner, schema_version="1.0"))
            self.ingest(self.make_payload(learner, schema_version="1.0"))
            log("2 events from an old app build (schema 1.0) migrated to 1.1.")
            return {
                "name": name,
                "steps": steps,
                "outcome": {"late": 8, "duplicates": 3, "migrated": 2},
            }

        raise KeyError(name)

    # --- startup history so the marts are not empty ---------------------------------------
    def seed_history(self, days: int = 21) -> None:
        now = datetime.now(tz=UTC)
        for learner in seed.LEARNERS:
            for day in range(days, 0, -1):
                weight = 1.0
                if learner.id == "l-004":  # declining engagement
                    weight = 1.6 if day > 14 else 0.7 if day > 7 else 0.15
                n = max(0, int(self.rng.gauss(4 * weight, 1.5)))
                for _ in range(n):
                    at = now - timedelta(days=day, minutes=self.rng.randint(0, 1400))
                    payload = self.make_payload(
                        learner, occurred_at=at, platform=self.rng.choice(["web", "android", "ios"])
                    )
                    self.ingest(
                        payload, received_at=at + timedelta(seconds=self.rng.randint(1, 20))
                    )
        for learner in seed.LEARNERS:
            for assignment in seed.ASSIGNMENTS:
                if assignment.course_id not in learner.course_ids or self.rng.random() < 0.3:
                    continue
                correct = self.rng.random() < (0.35 if learner.id == "l-004" else 0.75)
                failing = set() if correct else {t.id for t in assignment.tests[1:3]}
                self.submit(
                    learner.id,
                    assignment.id,
                    "# seeded history",
                    self.synthetic_log(
                        assignment,
                        True,
                        failing | ({"t5_pairs"} if assignment.id == "a-py-even" else set()),
                    ),
                )
        self.p.suppressed_count = 0
        self.p.risk_alerts.clear()

    def stats(self) -> dict[str, Any]:
        p = self.p
        graded = sum(s.result is not None for s in p.submissions.all())
        return {
            "bronze": len(p.bronze.rows),
            "silver": len(p.silver.events),
            "dlq": len(p.dlq.rows),
            "late_events": p.late_events,
            "topics": dict(p.bus.counts),
            "notifications_sent": p.notifications.count(),
            "notifications_suppressed": p.suppressed_count,
            "submissions_graded": graded,
            "risk_alerts": len(p.risk_alerts),
            "feature_rows": p.online_features.count(),
            "content_versions": sum(len(c.versions) for c in p.content.all()),
            "last_event_at": p.bus.last_at.isoformat() if p.bus.last_at else None,
        }
