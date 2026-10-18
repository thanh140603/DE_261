"""Version 1 source contracts. UTC timestamps, stable row keys, explicit statuses."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


def timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)):
        result = datetime.fromtimestamp(value / 1000, UTC)
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return result.astimezone(UTC)


def identity(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class Row(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=200)

    @field_validator(
        "student_id",
        "course_id",
        "assignment_id",
        "question_id",
        "submission_id",
        "test_case_id",
        check_fields=False,
    )
    @classmethod
    def nonempty_identifier(cls, value: str) -> str:
        if not value.strip() or len(value) > 200:
            raise ValueError("identifiers must contain 1 to 200 nonblank characters")
        return value


class Course(Row):
    title: str
    telemetry_enabled: bool
    created_at: AwareDatetime


class Assignment(Row):
    course_id: str
    title: str
    deadline: AwareDatetime | None = None
    required: bool = True
    published_at: AwareDatetime


class Question(Row):
    version: int = Field(gt=0)
    assignment_id: str
    title: str
    created_at: AwareDatetime


class TestCase(Row):
    version: int = Field(gt=0)
    question_id: str
    question_version: int = Field(gt=0)
    required: bool = True
    created_at: AwareDatetime


class Enrollment(Row):
    student_id: str
    course_id: str
    status: Literal["active", "completed", "withdrawn"]
    enrolled_at: AwareDatetime


class Submission(Row):
    student_id: str
    course_id: str
    assignment_id: str
    question_id: str
    question_version: int = Field(gt=0)
    submitted_at: AwareDatetime
    execution_status: Literal["evaluated", "pending", "infra_error"]


class Evaluation(Row):
    submission_id: str
    test_case_id: str
    test_case_version: int = Field(gt=0)
    status: Literal["passed", "failed", "error", "timeout", "skipped", "infra_error"]
    is_valid_evaluation: bool
    evaluated_at: AwareDatetime


class Activity(Row):
    student_id: str
    course_id: str
    event_type: Literal["lesson_view", "lesson_complete", "submission", "session"]
    event_time: AwareDatetime


class Clock(Row):
    evaluated_at: AwareDatetime


CONTRACTS: dict[str, type[Row]] = {
    "courses": Course,
    "assignments": Assignment,
    "questions": Question,
    "test_cases": TestCase,
    "enrollments": Enrollment,
    "submissions": Submission,
    "evaluations": Evaluation,
    "activity_events": Activity,
    "clocks": Clock,
}
TIME_FIELDS = {
    "created_at",
    "published_at",
    "deadline",
    "enrolled_at",
    "submitted_at",
    "evaluated_at",
    "event_time",
}


def validate_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for field in TIME_FIELDS & row.keys():
        if row[field] is not None:
            normalized[field] = timestamp(row[field])
    return CONTRACTS[table].model_validate(normalized).model_dump(mode="json")


def row_key(table: str, row: dict[str, Any]) -> str:
    return f"{row['id']}:{row['version']}" if table in {"questions", "test_cases"} else row["id"]
