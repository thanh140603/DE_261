"""Provision and seed the isolated classroom database once."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from secrets import token_bytes
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from edu_platform.demo import seed

from .classroom import ACCOUNTS, CLOCK_ID, enrollment_id, password_hash, save_grade
from .config import settings
from .db import Db, connect, migrate
from .fixtures import upsert

DATABASE = "br45_classroom"


def enrollment(conn: Db, student: str, course: str, at: datetime, status: str = "active") -> None:
    upsert(
        conn,
        "enrollments",
        {
            "id": enrollment_id(student, course),
            "student_id": student,
            "course_id": course,
            "enrolled_at": at,
            "status": status,
        },
    )


def attempt(
    conn: Db,
    assignment: seed.Assignment,
    student: str,
    at: datetime,
    index: int,
) -> dict[str, Any]:
    tests = []
    for test in assignment.tests:
        fail = (assignment.id == "a-py-even" and test.id == "t5_pairs" and index < 22) or (
            assignment.id != "a-py-even" and test == assignment.tests[0] and index < 6
        )
        tests.append(
            {
                "test_case_id": test.id,
                "status": "failed" if fail else "passed",
                "expected": test.expected,
                "actual": None if fail else test.expected,
                "diff": None,
                "duration_ms": 0,
            }
        )
    passed = sum(test["status"] == "passed" for test in tests)
    payload = {
        "id": f"classroom-initial-{student}-{assignment.id}",
        "learner_id": student,
        "assignment_id": assignment.id,
        "language": assignment.language,
        "attempt_number": 1,
        "submitted_at": at.isoformat(),
        "status": "graded",
        "result": {
            "stdout": "",
            "stderr": "",
            "runtime_ms": 0,
            "memory_kb": 0,
            "exit_code": 0,
            "pass_rate": passed / len(tests),
            "tests": tests,
        },
        "feedback": {
            "summary": f"Preset attempt passed {passed} of {len(tests)} tests",
            "failed_tests": [test for test in tests if test["status"] == "failed"],
            "stderr_excerpt": "",
            "hints": [],
        },
    }
    save_grade(conn, assignment, payload, at)
    return payload


def populate(conn: Db, password: str, at: datetime) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('br45-classroom-bootstrap'))")
    if conn.execute("SELECT 1 FROM classroom.run").fetchone():
        return
    if len(password) < 12:
        raise ValueError(
            "Set EDU_BR45_CLASSROOM_PASSWORD to at least 12 characters before initialization"
        )
    created = at - timedelta(days=40)
    due = at - timedelta(days=2)
    for course in seed.COURSES:
        upsert(
            conn,
            "courses",
            {
                "id": course.id,
                "title": course.title,
                "created_at": created,
                "telemetry_enabled": True,
            },
        )
    for learner in seed.LEARNERS:
        for course_id in learner.course_ids:
            enrollment(
                conn,
                learner.id,
                course_id,
                at - timedelta(days=1 if learner.id == "l-005" else 30),
                "completed" if (learner.id, course_id) == ("l-001", "c-sql-101") else "active",
            )
    for username, (student, profile) in ACCOUNTS.items():
        salt = token_bytes(16)
        conn.execute(
            "INSERT INTO classroom.accounts VALUES (%s,%s,%s,%s,%s)",
            (username, student, salt, password_hash(password, salt), profile),
        )
    for assignment in seed.ASSIGNMENTS:
        upsert(
            conn,
            "assignments",
            {
                "id": assignment.id,
                "course_id": assignment.course_id,
                "title": assignment.title,
                "required": assignment.id != "a-py-even",
                "published_at": created,
                "deadline": due if assignment.id != "a-py-even" else None,
            },
        )
        upsert(
            conn,
            "questions",
            {
                "id": assignment.id,
                "version": 1,
                "assignment_id": assignment.id,
                "title": assignment.title,
                "created_at": created,
            },
        )
        for test in assignment.tests:
            upsert(
                conn,
                "test_cases",
                {
                    "id": f"{assignment.id}-{test.id}",
                    "version": 1,
                    "question_id": assignment.id,
                    "question_version": 1,
                    "required": True,
                    "created_at": created,
                },
            )
        for index in range(24):
            student = f"classroom-cohort-{assignment.course_id}-{index + 1:02}"
            enrollment(conn, student, assignment.course_id, at - timedelta(days=30))
            attempt(conn, assignment, student, at - timedelta(days=3), index)
        if assignment.id == "a-py-fizz":
            for student in ("l-001", "l-004"):
                payload = attempt(conn, assignment, student, at - timedelta(days=3), 24)
                conn.execute(
                    "INSERT INTO classroom.feedback VALUES (%s,%s,'preset','preset',%s)",
                    (payload["id"], student, Jsonb(payload)),
                )
    for student, course_id, ages in (
        ("l-001", "c-py-201", (1, 2, 3)),
        ("l-003", "c-py-201", (8, 9, 10, 11)),
        ("l-004", "c-py-201", (1, 3)),
        ("l-006", "c-sql-101", (8, 9, 10, 11)),
    ):
        for days in ages:
            upsert(
                conn,
                "activity_events",
                {
                    "id": f"classroom-initial-{student}-{days}",
                    "student_id": student,
                    "course_id": course_id,
                    "event_type": "lesson_complete",
                    "event_time": at - timedelta(days=days),
                },
            )
    upsert(conn, "clocks", {"id": CLOCK_ID, "evaluated_at": at})
    conn.execute("INSERT INTO classroom.run DEFAULT VALUES")


def main() -> None:
    cfg = settings()
    if not cfg.classroom or conninfo_to_dict(cfg.dsn).get("dbname") != DATABASE:
        raise ValueError("Initialize only the isolated BR45 classroom database")
    password = os.environ.get("EDU_BR45_CLASSROOM_PASSWORD", "")
    with psycopg.connect(make_conninfo(cfg.dsn, dbname="postgres"), autocommit=True) as admin:
        if not admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DATABASE,)).fetchone():
            admin.execute("CREATE DATABASE br45_classroom")
    migrate(classroom=True)
    with connect() as conn:
        populate(conn, password, datetime.now(UTC).replace(minute=0, second=0, microsecond=0))
    print("Classroom database and preset profiles are ready")


if __name__ == "__main__":
    main()
