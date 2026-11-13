"""Use case: join the batch and streaming feature branches for one learner (BR2)."""

from __future__ import annotations

from edu_platform.contexts.recommendation.application.ports import OnlineFeatureStore
from edu_platform.contexts.recommendation.domain.model import LearnerFeatures


class LoadLearnerFeatures:
    def __init__(self, store: OnlineFeatureStore) -> None:
        self._store = store

    def execute(self, learner_pseudonym: str) -> LearnerFeatures:
        return LearnerFeatures(
            longterm=self._store.get_longterm(learner_pseudonym),
            session=self._store.get_session(learner_pseudonym),
        )
