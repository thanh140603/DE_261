"""Deterministic fixtures and a process-local clock for the BR45 presentation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

from .assessment import classify, python_baseline
from .config import AnalyticsSettings
from .risk import score

INTERVAL = 60
STAGES = ("Warning", "First response", "Activity returns", "Assignment submitted")
# Keep the scripted outcomes on the default policy even if the live policy is overridden.
POLICY = AnalyticsSettings.model_construct(slide_seconds=INTERVAL)


@dataclass(frozen=True)
class CourseScript:
    id: str
    title: str
    assignment: str
    questions: tuple[str, str, str]
    test: str
    passes: tuple[int, int, int, int]
    surnames: tuple[str, str, str, str]
    outreach: str
    missed: str
    newcomer: str

    def learner(self, index: int) -> str:
        return f"{self.id}-replay-{index + 1:02d}"


COURSES = {
    item.id: item
    for item in (
        CourseScript(
            "c-py-201",
            "Python for Data",
            "Data cleaning lab",
            ("Sum even numbers", "Normalize input rows", "Validate CSV headers"),
            "empty-input",
            (2, 8, 16, 22),
            ("Tran", "Phan", "Mai", "Le"),
            "Linh Dao",
            "Minh Chau",
            "Thu Bui",
        ),
        CourseScript(
            "c-sql-101",
            "SQL Foundations",
            "Joins and aggregation lab",
            ("Include customers with no orders", "Group orders by month", "Filter null totals"),
            "unmatched-customer",
            (4, 10, 17, 21),
            ("Nguyen", "Hoang", "Dang", "Do"),
            "An Nguyen",
            "Bao Ly",
            "Yen Lam",
        ),
        CourseScript(
            "c-de-301",
            "Data Engineering Basics",
            "Event processing lab",
            ("Deduplicate delayed events", "Parse event timestamps", "Validate event schemas"),
            "late-duplicate",
            (3, 9, 15, 20),
            ("Vo", "Vu", "Ngo", "Dinh"),
            "Mai Pham",
            "Khanh Ngo",
            "Tuan Ha",
        ),
    )
}
FIRST_NAMES = ("Anh", "Binh", "Chi", "Giang", "Han", "Quang")


def grading_facts(course: CourseScript, stage: int, anchor: datetime) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for index, title in enumerate(course.questions):
        question = f"{course.id}-replay-q{index + 1}"
        cases = ("standard", course.test, "boundary") if index == 0 else ("standard",)
        submitted = anchor - timedelta(days=4 - index)
        for learner in range(5 if index == 2 else 24):
            for case in cases:
                passed = (
                    learner < course.passes[stage]
                    if case == course.test
                    else index != 1 or learner < 21
                )
                facts.append(
                    {
                        "course_id": course.id,
                        "assignment_id": f"{course.id}-replay-lab",
                        "assignment_title": course.assignment,
                        "question_id": question,
                        "question_version": 1,
                        "question_title": title,
                        "submission_id": f"{question}-{learner + 1}",
                        "student_id": course.learner(learner),
                        "submitted_at": submitted,
                        "evaluated_at": submitted + timedelta(minutes=1),
                        "test_case_id": case,
                        "test_case_version": 1,
                        "status": "passed" if passed else "failed",
                        "valid": True,
                        "infra_error": False,
                    }
                )
    return facts


def risk_rows(
    course: CourseScript, stage: int, anchor: datetime, at: datetime
) -> list[dict[str, Any]]:
    due = f"{course.id}-replay-lab"
    assignments = [
        {
            "id": due,
            "course_id": course.id,
            "required": True,
            "published_at": anchor - timedelta(days=20),
            "deadline": anchor - timedelta(days=2),
        }
    ]
    names = [
        *(f"{first} {last}" for last in course.surnames for first in FIRST_NAMES),
        course.outreach,
        course.missed,
        course.newcomer,
    ]
    rows = []
    for index, name in enumerate(names):
        sid = course.learner(index)
        who = {"student_id": sid, "course_id": course.id}
        enrollment = {
            **who,
            "status": "active",
            "enrolled_at": anchor - timedelta(days=1 if index == 26 else 30),
        }
        if index == 24:
            previous = [anchor - timedelta(days=age) for age in range(8, 12)]
            recent = [at - timedelta(seconds=age) for age in range(1, (0, 1, 4, 5)[stage] + 1)]
        else:
            previous = []
            recent = [anchor - timedelta(hours=12)] if index != 26 else []
        submissions = []
        if index < 24 or (index == 24 and stage == 3):
            submissions.append(
                {
                    **who,
                    "assignment_id": due,
                    "execution_status": "evaluated",
                    "submitted_at": anchor - timedelta(days=3)
                    if index < 24
                    else at - timedelta(seconds=1),
                }
            )
        activities = [{**who, "event_time": event} for event in previous + recent]
        row = score(
            enrollment,
            {"telemetry_enabled": True},
            assignments,
            submissions,
            activities,
            at,
            len(recent),
            len(previous),
            POLICY,
        )
        rows.append(row | {"student_name": name, "computed_at": at.isoformat()})
    return sorted(rows, key=lambda row: (-row["score"], row["student_id"]))


def assessment_rows(
    course: CourseScript,
    stage: int,
    anchor: datetime,
    at: datetime,
    start: datetime,
    end: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts = grading_facts(course, stage, anchor)

    def aggregate(
        first: datetime, last: datetime
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return python_baseline(
            [
                row
                for row in facts
                if first <= row["submitted_at"] < last and row["evaluated_at"] < last
            ]
        )

    questions, cases = aggregate(start, end)

    def key(row: dict[str, Any]) -> str:
        return (
            f"{row['question_id']}/{row['test_case_id']}"
            if "test_case_id" in row
            else row["question_id"]
        )

    prior = {key(row): row for group in aggregate(start - (end - start), start) for row in group}
    for row in questions + cases:
        peers = [case for case in cases if case["question_id"] == row["question_id"]]
        row.update(classify(row, peers, prior.get(key(row)), POLICY))
        row.update(id=key(row), window_start=start, window_end=end, computed_at=at)
    return questions, cases


class Replay:
    """The server's async request handlers and timer share one event loop."""

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self.clock = clock
        self.deadline = clock() + INTERVAL
        self.revision = 0
        self.at = datetime.now(UTC)
        self.anchor = self.at
        self.risks: dict[str, list[dict[str, Any]]] = {}
        self.history: dict[str, list[dict[str, Any]]] = {}
        self.alerts: dict[str, dict[str, Any]] = {}
        self._publish()

    @property
    def stage(self) -> int:
        return self.revision % len(STAGES)

    def tick(self, expected: int | None = None) -> None:
        now = self.clock()
        if now < self.deadline and expected != self.revision:
            return
        self.deadline = now + INTERVAL
        self.revision += 1
        self.at = datetime.now(UTC)
        if self.stage == 0:
            self.anchor = self.at
            self.history.clear()
            self.alerts.clear()
        self._publish()

    def _publish(self) -> None:
        for course in COURSES.values():
            rows = risk_rows(course, self.stage, self.anchor, self.at)
            self.risks[course.id] = rows
            for row in rows:
                student = row["student_id"]
                self.history.setdefault(student, []).insert(0, row)
                alert_id = f"{student}-alert-{self.revision // len(STAGES)}"
                alert = self.alerts.get(alert_id)
                if row["score"] >= POLICY.alert_threshold:
                    if alert is None:
                        self.alerts[alert_id] = {
                            "id": alert_id,
                            "student_id": student,
                            "course_id": course.id,
                            "created_at": row["evaluated_at"],
                            "acknowledged_at": None,
                            "resolved_at": None,
                            "status": "NEW",
                            **{
                                field: row[field]
                                for field in ("score", "level", "reasons", "evaluated_at")
                            },
                        }
                    elif alert["status"] != "RESOLVED":
                        alert.update(
                            {
                                field: row[field]
                                for field in ("score", "level", "reasons", "evaluated_at")
                            }
                        )
                elif alert and alert["status"] != "RESOLVED":
                    self.update_alert(alert, "RESOLVED", row["evaluated_at"])

    @staticmethod
    def update_alert(alert: dict[str, Any], status: str, at: str) -> None:
        field = "acknowledged_at" if status == "ACKNOWLEDGED" else "resolved_at"
        alert.update({"status": status, field: alert[field] or at})

    def status(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "stage": self.stage + 1,
            "stage_count": len(STAGES),
            "label": STAGES[self.stage],
            "updated_at": self.at,
            "next_update_at": datetime.now(UTC)
            + timedelta(seconds=max(0, self.deadline - self.clock())),
        }
