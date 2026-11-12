"""Durable classroom source writes shared by signed-in students and study bots."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from edu_platform.demo import seed
from edu_platform.demo.serializers import submission_dict
from edu_platform.demo.simulator import Simulator
from edu_platform.shared_kernel.domain.ids import SubmissionId

from .contracts import identity, timestamp
from .db import Db, connect, state
from .fixtures import upsert

ACCOUNTS = {
    "an.demo": ("l-001", "Established learner with completed work and recent activity"),
    "chi.demo": ("l-003", "Established learner with an overdue Python lab and a risk warning"),
    "ha.demo": ("l-005", "New enrollment with limited activity and grading history"),
}
CLOCK_ID = "classroom-clock"


class StudyError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


def password_hash(password: str, salt: bytes) -> bytes:
    # scrypt is available in the existing image through the Python standard library.
    return hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=3, maxmem=64 * 1024**2)


def logical_clock(conn: Db) -> datetime:
    clock = state(conn, "evaluation_clock")
    if clock is None:
        raise StudyError(503, "Wait for the classroom pipeline to initialize its clock")
    return timestamp(clock)


def enrollment_id(student: str, course: str) -> str:
    return f"classroom-{student}-{course}"


def active(conn: Db, student: str, course: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM br45.enrollments WHERE student_id=%s AND course_id=%s AND status='active'",
        (student, course),
    ).fetchone()
    if row is None:
        raise StudyError(403, "This action requires an active course enrollment")


def change_enrollment(student: str, course: str, complete: bool) -> None:
    with connect() as conn:
        if complete:
            changed = conn.execute(
                "UPDATE br45.enrollments SET status='completed' "
                "WHERE student_id=%s AND course_id=%s",
                (student, course),
            ).rowcount
            if not changed:
                raise StudyError(403, "Enroll in this course before completing it")
        else:
            at = logical_clock(conn)
            conn.execute(
                "INSERT INTO br45.enrollments (id,student_id,course_id,status,enrolled_at) "
                "VALUES (%s,%s,%s,'active',%s) ON CONFLICT (student_id,course_id) DO NOTHING",
                (enrollment_id(student, course), student, course, at - timedelta(seconds=1)),
            )


def load_enrollments(simulator: Simulator) -> None:
    with connect() as conn:
        for learner in seed.LEARNERS:
            rows = list(
                conn.execute(
                    "SELECT course_id,status FROM br45.enrollments "
                    "WHERE student_id=%s ORDER BY course_id",
                    (learner.id,),
                )
            )
            simulator.p.enrollments[learner.id] = [row["course_id"] for row in rows]
            simulator.p.completed_courses[learner.id] = [
                row["course_id"] for row in rows if row["status"] == "completed"
            ]


def lesson_progress(student: str) -> list[dict[str, Any]]:
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT lesson_id, started_at, completed_at FROM classroom.lesson_progress "
                "WHERE student_id=%s ORDER BY lesson_id",
                (student,),
            )
        )


def lesson_activity(student: str, lesson_id: str, kind: str, request_id: str) -> None:
    course = next(
        (
            item.id
            for item in seed.COURSES
            if any(lesson.id == lesson_id for lesson in item.lessons)
        ),
        None,
    )
    if course is None:
        raise StudyError(404, "Lesson not found")
    event = identity("classroom-lesson", student, lesson_id, kind, request_id)
    with connect() as conn:
        active(conn, student, course)
        at = logical_clock(conn)
        changed = conn.execute(
            "INSERT INTO br45.activity_events (id,student_id,course_id,event_type,event_time) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (event, student, course, kind, at - timedelta(milliseconds=1)),
        ).rowcount
        if changed:
            conn.execute(
                "INSERT INTO classroom.lesson_progress (student_id, lesson_id, completed_at) "
                "VALUES (%s,%s,CASE WHEN %s THEN now() END) "
                "ON CONFLICT (student_id,lesson_id) DO UPDATE "
                "SET completed_at=coalesce(classroom.lesson_progress.completed_at,"
                "excluded.completed_at)",
                (student, lesson_id, kind == "lesson_complete"),
            )


def save_grade(
    conn: Db,
    assignment: seed.Assignment,
    result: dict[str, Any],
    at: datetime,
) -> None:
    submission = result["id"]
    student = result["learner_id"]
    graded = result["status"] == "graded"
    upsert(
        conn,
        "submissions",
        {
            "id": submission,
            "student_id": student,
            "course_id": assignment.course_id,
            "assignment_id": assignment.id,
            "question_id": assignment.id,
            "question_version": 1,
            "submitted_at": at,
            "execution_status": "evaluated" if graded else "infra_error",
        },
    )
    tests = result["result"]["tests"] if result["result"] else []
    expected = {test.id for test in assignment.tests}
    for test in tests:
        test_id = test["test_case_id"]
        if test_id in expected:
            upsert(
                conn,
                "evaluations",
                {
                    "id": identity(submission, test_id),
                    "submission_id": submission,
                    "test_case_id": f"{assignment.id}-{test_id}",
                    "test_case_version": 1,
                    "status": test["status"],
                    "is_valid_evaluation": graded,
                    "evaluated_at": at + timedelta(microseconds=1),
                },
            )


def submit(
    sim: Simulator,
    student: str,
    assignment_id: str,
    code: str,
    request_id: str,
) -> str:
    assignment = next((row for row in seed.ASSIGNMENTS if row.id == assignment_id), None)
    if assignment is None:
        raise StudyError(404, "Assignment not found")
    request_hash = identity(assignment_id, code)
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"classroom-grade:{student}",))
        prior = conn.execute(
            "SELECT submission_id,request_hash FROM classroom.feedback "
            "WHERE student_id=%s AND request_id=%s",
            (student, request_id),
        ).fetchone()
        if prior:
            if prior["request_hash"] != request_hash:
                raise StudyError(409, "This request ID already belongs to another submission")
            return str(prior["submission_id"])
        active(conn, student, assignment.course_id)
        at = logical_clock(conn)
        number = conn.execute(
            "SELECT count(*)+1 AS n FROM br45.submissions WHERE student_id=%s AND assignment_id=%s",
            (student, assignment.id),
        ).fetchone()
        assert number is not None
        received = sim.submit(student, assignment.id, code)
        finished = sim.p.submissions.get(SubmissionId(received.id))
        if finished is None or finished.status.value not in {"graded", "failed"}:
            raise StudyError(503, "The sandbox did not finish grading. Try submitting again.")
        result = submission_dict(finished) | {"attempt_number": number["n"]}
        event_time = at - timedelta(seconds=1) + timedelta(microseconds=min(number["n"], 900000))
        save_grade(conn, assignment, result, event_time)
        conn.execute(
            "INSERT INTO classroom.feedback VALUES (%s,%s,%s,%s,%s)",
            (received.id, student, request_id, request_hash, Jsonb(result)),
        )
        if finished.status.value == "graded":
            upsert(
                conn,
                "activity_events",
                {
                    "id": identity("classroom-submission", received.id),
                    "student_id": student,
                    "course_id": assignment.course_id,
                    "event_type": "submission",
                    "event_time": event_time,
                },
            )
        return str(received.id)


def feedback(student: str, submission_id: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        return [
            row["payload"]
            for row in conn.execute(
                "SELECT payload FROM classroom.feedback WHERE student_id=%s "
                "AND (%s::text IS NULL OR submission_id=%s) ORDER BY payload->>'submitted_at' DESC",
                (student, submission_id, submission_id),
            )
        ]
