"""In-memory risk adapters (tests + demo)."""

from __future__ import annotations

from edu_platform.contexts.risk.domain.model import LearnerRiskProfile


class InMemoryRiskProfileRepository:
    def __init__(self) -> None:
        self._rows: dict[str, LearnerRiskProfile] = {}

    def get(self, profile_id: str) -> LearnerRiskProfile | None:
        return self._rows.get(profile_id)

    def save(self, profile: LearnerRiskProfile) -> None:
        self._rows[profile.id] = profile

    def all(self) -> list[LearnerRiskProfile]:
        return list(self._rows.values())


class InMemoryRiskScoreStore:
    def __init__(self) -> None:
        self.scores: dict[tuple[str, str], float] = {}

    def put(self, learner_id: str, course_id: str, score: float, ttl_seconds: int) -> None:
        self.scores[(learner_id, course_id)] = score
