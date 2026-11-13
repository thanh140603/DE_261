from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from edu_platform.shared_kernel.domain import DomainEvent
from edu_platform.shared_kernel.domain.ids import AssignmentId, LearnerId


@dataclass(frozen=True, kw_only=True)
class SubmissionReceived(DomainEvent):
    event_type: ClassVar[str] = "grading.submission_received.v1"
    learner_id: LearnerId


@dataclass(frozen=True, kw_only=True)
class SubmissionGraded(DomainEvent):
    event_type: ClassVar[str] = "grading.submission_graded.v1"
    learner_id: LearnerId
    assignment_id: AssignmentId
    pass_rate: float
    # Snapshot fields let the projector upsert a complete LMS row even when the
    # graded event arrives before the queued event (different topics).
    language: str
    code_ref: str
    attempt_number: int
    submitted_at: datetime
