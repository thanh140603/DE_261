from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from edu_platform.shared_kernel.domain import AggregateRoot, InvariantViolation, ValueObject
from edu_platform.shared_kernel.domain.ids import CourseId, LearnerId

from .events import DropoutRiskDetected


class SignalKind(StrEnum):
    """Observable behaviours that feed the score. Each maps to a CDC table or telemetry verb."""

    PROGRESS_STALLED = "progress_stalled"
    DEADLINE_MISSED = "deadline_missed"
    GRADE_DECLINING = "grade_declining"
    LOGIN_GAP = "login_gap"
    REPEATED_FAILURES = "repeated_failures"


@dataclass(frozen=True)
class RiskSignal(ValueObject):
    kind: SignalKind
    weight: float  # contribution in [0, 1]
    observed_at: datetime

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise InvariantViolation("signal weight must be within [0, 1]")


@dataclass(frozen=True)
class RiskScore(ValueObject):
    value: float
    computed_at: datetime

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise InvariantViolation("risk score must be within [0, 1]")


@dataclass(frozen=True)
class SlidingWindowPolicy(ValueObject):
    """Window shape for the streaming job and alert threshold - owned by the business."""

    window_size: timedelta = timedelta(days=14)
    slide: timedelta = timedelta(days=1)
    alert_threshold: float = 0.7
    cooldown: timedelta = timedelta(days=3)


@dataclass(eq=False, kw_only=True)
class LearnerRiskProfile(AggregateRoot[str]):
    """Aggregate keyed by (learner, course). id = f"{learner_id}:{course_id}"."""

    learner_id: LearnerId
    course_id: CourseId
    signals: list[RiskSignal] = field(default_factory=list)
    score: RiskScore | None = None
    history: list[RiskScore] = field(default_factory=list)
    last_alert_at: datetime | None = None

    @staticmethod
    def key(learner_id: str, course_id: str) -> str:
        return f"{learner_id}:{course_id}"

    def observe(
        self, signals: list[RiskSignal], policy: SlidingWindowPolicy, now: datetime
    ) -> None:
        """Append signals and evict everything outside the sliding window."""
        self.signals.extend(signals)
        cutoff = now - policy.window_size
        self.signals = [s for s in self.signals if s.observed_at >= cutoff]

    def rescore(self, score: RiskScore, policy: SlidingWindowPolicy) -> None:
        self.score = score
        self.history.append(score)
        self.history = self.history[-50:]
        if score.value >= policy.alert_threshold and self._cooldown_elapsed(
            score.computed_at, policy
        ):
            self.last_alert_at = score.computed_at
            top: list[SignalKind] = []
            for s in sorted(self.signals, key=lambda s: -s.weight):
                if s.kind not in top:
                    top.append(s.kind)
            self.record(
                DropoutRiskDetected(
                    aggregate_id=self.id,
                    learner_id=self.learner_id,
                    course_id=self.course_id,
                    score=score.value,
                    top_signals=tuple(top[:3]),
                )
            )

    def _cooldown_elapsed(self, now: datetime, policy: SlidingWindowPolicy) -> bool:
        return self.last_alert_at is None or now - self.last_alert_at >= policy.cooldown
