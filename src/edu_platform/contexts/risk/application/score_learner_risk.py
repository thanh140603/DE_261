"""Use case executed per keyed record inside the Flink job, or in-process in the demo (BR5).

For each (learner, course): observe new signals into the sliding window, score
with RiskScoringPolicy, persist, publish DropoutRiskDetected when the threshold
is crossed (respecting cooldown) and refresh the online score.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from edu_platform.contexts.risk.application.ports import RiskProfileRepository, RiskScoreStore
from edu_platform.contexts.risk.domain.model import (
    LearnerRiskProfile,
    RiskSignal,
    SlidingWindowPolicy,
)
from edu_platform.contexts.risk.domain.scoring_policy import RiskScoringPolicy
from edu_platform.shared_kernel.application import EventPublisher
from edu_platform.shared_kernel.domain.ids import CourseId, LearnerId


@dataclass(frozen=True)
class ScoreLearnerRiskCommand:
    learner_id: str
    course_id: str
    signals: list[RiskSignal]
    as_of: datetime


@dataclass(frozen=True)
class ScoreLearnerRiskResult:
    score: float
    alerted: bool


class ScoreLearnerRisk:
    def __init__(
        self,
        repo: RiskProfileRepository,
        scoring: RiskScoringPolicy,
        policy: SlidingWindowPolicy,
        score_store: RiskScoreStore,
        publisher: EventPublisher,
    ) -> None:
        self._repo = repo
        self._scoring = scoring
        self._policy = policy
        self._score_store = score_store
        self._publisher = publisher

    def execute(self, command: ScoreLearnerRiskCommand) -> ScoreLearnerRiskResult:
        key = LearnerRiskProfile.key(command.learner_id, command.course_id)
        profile = self._repo.get(key) or LearnerRiskProfile(
            id=key, learner_id=LearnerId(command.learner_id), course_id=CourseId(command.course_id)
        )
        profile.observe(command.signals, self._policy, command.as_of)
        score = self._scoring.score(profile.signals, command.as_of)
        profile.rescore(score, self._policy)
        self._repo.save(profile)
        self._score_store.put(
            command.learner_id,
            command.course_id,
            score.value,
            int(self._policy.window_size.total_seconds() * 2),
        )
        events = profile.pull_events()
        if events:
            self._publisher.publish(events)
        return ScoreLearnerRiskResult(score=score.value, alerted=bool(events))
