"""Versioned analytical/API output contracts; additional diagnostic fields are retained."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Output(BaseModel):
    model_config = ConfigDict(extra="allow")


class Page(Output, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


class Metric(Output):
    id: str
    course_id: str
    assignment_id: str
    question_id: str
    question_version: int
    total_valid_evaluations: int
    passed_evaluations: int
    failed_evaluations: int
    unique_students: int
    invalid_evaluations: int
    infrastructure_errors: int
    pass_rate: float | None
    state: Literal[
        "NORMAL", "INSUFFICIENT_DATA", "LOW_PASS_RATE", "SUSPICIOUS_TEST_CASE", "NEEDS_REVIEW"
    ]
    severity: Literal["INFO", "MEDIUM", "HIGH"]
    reasons: list[str]
    threshold: float
    minimum_students: int
    window_start: datetime
    window_end: datetime


class RiskReason(Output):
    signal: str
    points: int
    reason: str


class Risk(Output):
    student_id: str
    course_id: str
    score: int
    level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    eligible: bool
    evaluated_at: datetime
    reasons: list[RiskReason]
    features: dict[str, Any]
    policy: dict[str, Any]


class RiskPage(Page[Risk]):
    summary: dict[str, Any]


class StudentRisk(Output):
    student_id: str
    courses: list[Risk]


class Alert(Output):
    id: str
    student_id: str
    course_id: str
    score: int
    level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    reasons: list[RiskReason]
    status: Literal["NEW", "ACKNOWLEDGED", "RESOLVED"]
    evaluated_at: datetime
    created_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None


class JobStatus(Output):
    id: str
    course_id: str
    window_start: datetime
    window_end: datetime
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]
    requested_revision: str | None
    published_revision: str | None
    publication_id: str | None
    source_delta_version: int | None
    engine: Literal["postgres", "spark"]
    published_engine: Literal["postgres", "spark"] | None
    completed_at: datetime | None
    error: str | None


class AssessmentPage(Page[Metric]):
    window_start: datetime
    window_end: datetime
    materialization_status: str
    job_id: str | None
    computed_at: datetime | None
    engine: str
    error: str | None
    published_revision: str | None
    pending_revision: str | None
    publication_id: str | None
    source_delta_version: int | None
    stale: bool
