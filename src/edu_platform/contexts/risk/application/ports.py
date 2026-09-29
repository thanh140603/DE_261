from __future__ import annotations

from typing import Protocol

from edu_platform.contexts.risk.domain.model import LearnerRiskProfile


class RiskProfileRepository(Protocol):
    def get(self, profile_id: str) -> LearnerRiskProfile | None: ...

    def save(self, profile: LearnerRiskProfile) -> None: ...

    def all(self) -> list[LearnerRiskProfile]: ...


class RiskScoreStore(Protocol):
    """Online store read by advisor dashboards (Redis in production)."""

    def put(self, learner_id: str, course_id: str, score: float, ttl_seconds: int) -> None: ...
