"""In-memory long-term feature store (tests; BR2-lite does not serve it)."""

from __future__ import annotations

from edu_platform.contexts.recommendation.domain.model import LongTermFeatures


class InMemoryOnlineFeatureStore:
    def __init__(self) -> None:
        self._longterm: dict[str, LongTermFeatures] = {}

    def put_longterm(self, features: LongTermFeatures) -> None:
        self._longterm[features.learner_pseudonym] = features

    def get_longterm(self, learner_pseudonym: str) -> LongTermFeatures | None:
        return self._longterm.get(learner_pseudonym)

    def count(self) -> int:
        return len(self._longterm)
