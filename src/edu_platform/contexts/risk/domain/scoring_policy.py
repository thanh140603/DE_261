"""Domain service: combine RiskSignals in a window into a RiskScore.

v1 is a noisy-OR of recency-decayed signal weights: independent evidence
accumulates towards 1 without ever exceeding it, and old evidence fades with a
half-life. A trained model can replace it behind the same interface.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from .model import RiskScore, RiskSignal


class RiskScoringPolicy:
    def __init__(self, half_life: timedelta = timedelta(days=7)) -> None:
        self._half_life = half_life

    def score(self, signals: list[RiskSignal], as_of: datetime) -> RiskScore:
        survival = 1.0
        for s in signals:
            age_days = max(0.0, (as_of - s.observed_at).total_seconds() / 86400)
            decay = math.pow(0.5, age_days / (self._half_life.total_seconds() / 86400))
            survival *= 1.0 - min(1.0, s.weight * decay)
        return RiskScore(value=round(min(1.0, max(0.0, 1.0 - survival)), 4), computed_at=as_of)
