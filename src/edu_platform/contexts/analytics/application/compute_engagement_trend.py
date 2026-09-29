"""Use case BR8: windowed engagement score per learner/course + declining flag."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from edu_platform.contexts.analytics.domain.engagement_policy import EngagementPolicy
from edu_platform.contexts.analytics.domain.model import TimeWindow
from edu_platform.contexts.telemetry.domain.events import LearningEvent


@dataclass(frozen=True)
class EngagementSeries:
    learner_pseudonym: str
    course_id: str
    scores: list[float]
    declining: bool


@dataclass(frozen=True)
class EngagementTrend:
    windows: list[TimeWindow]
    series: list[EngagementSeries]
    course_avg: list[float]


class ComputeEngagementTrend:
    def __init__(self, policy: EngagementPolicy) -> None:
        self._policy = policy

    def execute(
        self,
        events: list[LearningEvent],
        course_id: str,
        as_of: datetime,
        window: timedelta,
        n_windows: int,
    ) -> EngagementTrend:
        windows = [
            TimeWindow(as_of - window * (n_windows - i), as_of - window * (n_windows - i - 1))
            for i in range(n_windows)
        ]
        counts: dict[str, list[dict[str, int]]] = defaultdict(
            lambda: [defaultdict(int) for _ in windows]
        )
        for e in events:
            if e.course_id != course_id:
                continue
            for i, w in enumerate(windows):
                if w.start <= e.occurred_at < w.end:
                    counts[e.learner_pseudonym][i][e.verb.value] += 1
                    break
        series = [
            EngagementSeries(p, course_id, scores, self._policy.is_declining(scores))
            for p, per_window in sorted(counts.items())
            for scores in [[self._policy.score(c) for c in per_window]]
        ]
        avg = [
            round(sum(s.scores[i] for s in series) / len(series), 2) if series else 0.0
            for i in range(n_windows)
        ]
        return EngagementTrend(windows, series, avg)
