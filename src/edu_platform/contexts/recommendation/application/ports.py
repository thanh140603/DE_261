from __future__ import annotations

from typing import Protocol

from edu_platform.contexts.recommendation.domain.model import LongTermFeatures


class OnlineFeatureStore(Protocol):
    """Optional cache for the offline features; BR2-lite does not require it."""

    def put_longterm(self, features: LongTermFeatures) -> None: ...

    def get_longterm(self, learner_pseudonym: str) -> LongTermFeatures | None: ...

    def count(self) -> int: ...


class OfflineFeatureStore(Protocol):
    """Delta tables features.<group>; point-in-time reads for training."""

    def append_longterm(self, rows: list[LongTermFeatures]) -> None: ...
