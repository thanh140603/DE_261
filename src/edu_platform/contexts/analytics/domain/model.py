from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from edu_platform.shared_kernel.domain import InvariantViolation, ValueObject
from edu_platform.shared_kernel.domain.ids import AssignmentId, ContentId, CourseId, OrganisationId


@dataclass(frozen=True)
class TimeWindow(ValueObject):
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise InvariantViolation("window end must be after start")

    @property
    def size(self) -> timedelta:
        return self.end - self.start


# --- BR4 ----------------------------------------------------------------------
@dataclass(frozen=True)
class AnomalyThreshold(ValueObject):
    """A test case is anomalous when its pass rate is far below the assignment's median."""

    min_attempts: int = 30  # statistical floor
    max_pass_rate: float = 0.35
    min_delta_from_median: float = 0.30


@dataclass(frozen=True)
class AssessmentItemStats(ValueObject):
    assignment_id: AssignmentId
    item_id: str  # question or test_case id
    attempts: int
    passes: int
    pass_rate: float
    assignment_median_pass_rate: float
    is_anomalous: bool
    window: TimeWindow


# --- BR6 ----------------------------------------------------------------------
@dataclass(frozen=True)
class MinCohortPolicy(ValueObject):
    """k-anonymity guard: aggregates below ``k`` learners are suppressed."""

    k: int = 5


@dataclass(frozen=True)
class OrgProgressReport(ValueObject):
    organisation_id: OrganisationId
    course_id: CourseId
    skill: str
    cohort_size: int
    completion_rate: float | None  # None when suppressed by MinCohortPolicy
    avg_mastery: float | None
    as_of: date


# --- BR7 ----------------------------------------------------------------------
class InteractionKind(StrEnum):
    PLAY = "play"
    PAUSE = "pause"
    SEEK = "seek"


@dataclass(frozen=True)
class HeatmapBucket(ValueObject):
    content_id: ContentId
    second: int
    play_count: int
    pause_count: int
    seek_count: int
    unique_learners: int


# --- BR8 ----------------------------------------------------------------------
@dataclass(frozen=True)
class EngagementWeights(ValueObject):
    login: float = 1.0
    view: float = 1.0
    attempt: float = 2.0
    discussion: float = 1.5


@dataclass(frozen=True)
class EngagementScore(ValueObject):
    learner_pseudonym: str
    course_id: CourseId
    window: TimeWindow
    score: float
    delta_vs_previous: float  # negative = declining
    declining: bool
