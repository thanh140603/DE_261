from __future__ import annotations

from dataclasses import dataclass
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
