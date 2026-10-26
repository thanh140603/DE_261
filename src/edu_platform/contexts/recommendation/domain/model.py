from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from edu_platform.shared_kernel.domain import InvariantViolation, ValueObject


class FeatureBranch(StrEnum):
    BATCH = "batch"
    STREAMING = "streaming"


class FeatureType(StrEnum):
    FLOAT = "float"
    INT = "int"
    STRING = "string"
    FLOAT_LIST = "float_list"


@dataclass(frozen=True)
class FeatureDefinition(ValueObject):
    """Registry entry: name, type, owning branch, freshness SLA (schemas/features/v1)."""

    name: str
    dtype: FeatureType
    branch: FeatureBranch
    freshness_sla: timedelta
    description: str = ""


@dataclass(frozen=True)
class FeatureGroup(ValueObject):
    name: str
    entity: str  # "learner" | "learner_course"
    features: tuple[FeatureDefinition, ...]
    version: int = 1


@dataclass(frozen=True)
class LongTermFeatures(ValueObject):
    """Batch-branch output. Keyed by pseudonym: features never carry raw identifiers."""

    learner_pseudonym: str
    completion_rate_30d: float
    avg_pass_rate_30d: float
    active_days_30d: int
    preferred_platform: str
    skill_mastery: dict[str, float]
    computed_at: datetime

    def __post_init__(self) -> None:
        if not 0.0 <= self.completion_rate_30d <= 1.0:
            raise InvariantViolation("completion rate must be within [0, 1]")


@dataclass(frozen=True)
class Recommendation(ValueObject):
    course_id: str
    lesson_id: str | None
    title: str
    reason: str
    score: float = 0.0
