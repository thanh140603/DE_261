"""In-memory online feature store (tests + demo). Redis adapter: redis_online_store.py (TODO)."""

from __future__ import annotations

from edu_platform.contexts.recommendation.domain.model import LongTermFeatures, SessionFeatures


class InMemoryOnlineFeatureStore:
    def __init__(self) -> None:
        self._longterm: dict[str, LongTermFeatures] = {}
        self._session: dict[str, SessionFeatures] = {}

    def put_longterm(self, features: LongTermFeatures) -> None:
        self._longterm[features.learner_pseudonym] = features

    def put_session(self, features: SessionFeatures) -> None:
        self._session[features.learner_pseudonym] = features

    def get_longterm(self, learner_pseudonym: str) -> LongTermFeatures | None:
        return self._longterm.get(learner_pseudonym)

    def get_session(self, learner_pseudonym: str) -> SessionFeatures | None:
        return self._session.get(learner_pseudonym)

    def count(self) -> int:
        return len(self._longterm) + len(self._session)
