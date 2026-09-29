from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from edu_platform.shared_kernel.domain import DomainEvent
from edu_platform.shared_kernel.domain.ids import CourseId, LearnerId


@dataclass(frozen=True, kw_only=True)
class DropoutRiskDetected(DomainEvent):
    event_type: ClassVar[str] = "risk.dropout_risk_detected.v1"
    learner_id: LearnerId
    course_id: CourseId
    score: float
    top_signals: tuple[str, ...]
