"""Explicitly SYNTHETIC fixtures. Stable ids make seeding repeatable without duplication."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from psycopg import sql

from .contracts import CONTRACTS
from .db import Db

PREFIX = "br45-demo-"
COURSE = "c-py-201"


def upsert(conn: Db, table: str, row: dict[str, Any]) -> None:
    if table not in CONTRACTS:
        raise ValueError(table)
    keys = ["id", "version"] if table in {"questions", "test_cases"} else ["id"]
    columns = list(row)
    update = [c for c in columns if c not in keys]
    query = sql.SQL(
        "INSERT INTO br45.{} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}"
    ).format(
        sql.Identifier(table),
        sql.SQL(",").join(map(sql.Identifier, columns)),
        sql.SQL(",").join(sql.Placeholder() for _ in columns),
        sql.SQL(",").join(map(sql.Identifier, keys)),
        sql.SQL(",").join(
            sql.SQL("{}=excluded.{}").format(sql.Identifier(c), sql.Identifier(c)) for c in update
        ),
    )
    conn.execute(query, [row[c] for c in columns])


def seed(conn: Db, at: datetime, students: int = 24) -> dict[str, Any]:
    from edu_platform.demo import seed as reference

    conn.execute("DELETE FROM br45.activity_events WHERE id LIKE %s", (PREFIX + "recovery-%",))
    created = at - timedelta(days=40)
    for c in reference.COURSES:
        upsert(
            conn,
            "courses",
            {"id": c.id, "title": c.title, "telemetry_enabled": True, "created_at": created},
        )
    assignment = PREFIX + "assignment"
    question = PREFIX + "question"
    upsert(
        conn,
        "assignments",
        {
            "id": assignment,
            "course_id": COURSE,
            "title": "SYNTHETIC: Review sum of even numbers",
            "required": True,
            "published_at": created,
            "deadline": at - timedelta(days=2),
        },
    )
    upsert(
        conn,
        "questions",
        {
            "id": question,
            "version": 1,
            "assignment_id": assignment,
            "title": "SYNTHETIC: Sum even numbers",
            "created_at": created,
        },
    )
    for i in range(3):
        upsert(
            conn,
            "test_cases",
            {
                "id": PREFIX + f"case-{i}",
                "version": 1,
                "question_id": question,
                "question_version": 1,
                "required": True,
                "created_at": created,
            },
        )
    for i in range(students):
        sid = PREFIX + f"student-{i:03}"
        upsert(
            conn,
            "enrollments",
            {
                "id": PREFIX + f"enrollment-{i}",
                "student_id": sid,
                "course_id": COURSE,
                "status": "active",
                "enrolled_at": at - timedelta(days=30),
            },
        )
        subid = PREFIX + f"submission-{i}"
        upsert(
            conn,
            "submissions",
            {
                "id": subid,
                "student_id": sid,
                "course_id": COURSE,
                "assignment_id": assignment,
                "question_id": question,
                "question_version": 1,
                "submitted_at": at - timedelta(days=3),
                "execution_status": "evaluated",
            },
        )
        for j in range(3):
            upsert(
                conn,
                "evaluations",
                {
                    "id": PREFIX + f"evaluation-{i}-{j}",
                    "submission_id": subid,
                    "test_case_id": PREFIX + f"case-{j}",
                    "test_case_version": 1,
                    "status": "failed" if j == 1 and i >= 2 else "passed",
                    "is_valid_evaluation": True,
                    "evaluated_at": at - timedelta(days=3) + timedelta(seconds=30),
                },
            )
        upsert(
            conn,
            "activity_events",
            {
                "id": PREFIX + f"active-{i}",
                "student_id": sid,
                "course_id": COURSE,
                "event_type": "lesson_complete",
                "event_time": at - timedelta(days=1),
            },
        )
    for name, age in (("at-risk", 30), ("active", 30), ("new", 2), ("no-telemetry", 30)):
        sid = PREFIX + name
        upsert(
            conn,
            "enrollments",
            {
                "id": PREFIX + "enrollment-" + name,
                "student_id": sid,
                "course_id": COURSE,
                "status": "active",
                "enrolled_at": at - timedelta(days=age),
            },
        )
        if name in {"at-risk", "active"}:
            for j in range(4):
                upsert(
                    conn,
                    "activity_events",
                    {
                        "id": PREFIX + f"{name}-baseline-{j}",
                        "student_id": sid,
                        "course_id": COURSE,
                        "event_type": "lesson_view",
                        "event_time": at - timedelta(days=8 + j),
                    },
                )
        if name == "active":
            for j in range(4):
                upsert(
                    conn,
                    "activity_events",
                    {
                        "id": PREFIX + f"{name}-recent-{j}",
                        "student_id": sid,
                        "course_id": COURSE,
                        "event_type": "lesson_complete",
                        "event_time": at - timedelta(hours=1 + j),
                    },
                )
    # Explicit clock last; Debezium may interleave topics, so metadata also emits refresh ticks.
    upsert(conn, "clocks", {"id": PREFIX + "clock", "evaluated_at": at})
    return {
        "synthetic": True,
        "evaluated_at": at.isoformat(),
        "course_id": COURSE,
        "question_id": question,
        "expected": {
            "question_valid": students,
            "question_passed": 2,
            "question_pass_rate": 2 / students,
            "suspicious_case": PREFIX + "case-1",
            "at_risk_student": PREFIX + "at-risk",
            "at_risk_score": 100,
            "new_student_score": 0,
        },
    }


def recover(conn: Db, at: datetime) -> None:
    for j in range(4):
        upsert(
            conn,
            "activity_events",
            {
                "id": PREFIX + f"recovery-{j}",
                "student_id": PREFIX + "at-risk",
                "course_id": COURSE,
                "event_type": "lesson_complete",
                "event_time": at - timedelta(minutes=1 + j),
            },
        )


def reset(conn: Db) -> None:
    """Delete only this fixture's OLTP records. Deletes flow through CDC, preserving audit."""
    for table in (
        "evaluations",
        "activity_events",
        "submissions",
        "enrollments",
        "test_cases",
        "questions",
        "assignments",
        "clocks",
    ):
        conn.execute(
            sql.SQL("DELETE FROM br45.{} WHERE id LIKE %s").format(sql.Identifier(table)),
            (PREFIX + "%",),
        )
