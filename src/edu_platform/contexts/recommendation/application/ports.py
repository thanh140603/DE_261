from __future__ import annotations

from typing import Protocol

from edu_platform.contexts.recommendation.domain.model import LongTermFeatures, SessionFeatures


class OnlineFeatureStore(Protocol):
    """Redis in production; keyed by learner pseudonym with TTL = freshness SLA."""

    def put_longterm(self, features: LongTermFeatures) -> None: ...

    def put_session(self, features: SessionFeatures) -> None: ...

    def get_longterm(self, learner_pseudonym: str) -> LongTermFeatures | None: ...

    def get_session(self, learner_pseudonym: str) -> SessionFeatures | None: ...

    def count(self) -> int: ...


class OfflineFeatureStore(Protocol):
    """Delta tables gold.features_<group>; point-in-time reads for training (TODO)."""

    def append_longterm(self, rows: list[LongTermFeatures]) -> None: ...
