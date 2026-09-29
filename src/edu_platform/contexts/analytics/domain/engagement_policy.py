"""Domain service (BR8): engagement score + declining-trend detection."""

from __future__ import annotations

from .model import EngagementWeights

_VERB_TO_WEIGHT = {
    "logged_in": "login",
    "viewed": "view",
    "played": "view",
    "completed": "view",
    "attempted": "attempt",
    "submitted": "attempt",
    "posted": "discussion",
}


class EngagementPolicy:
    def __init__(self, weights: EngagementWeights, decline_ratio: float = 0.30) -> None:
        self._weights = weights
        self._decline_ratio = decline_ratio

    def score(self, verb_counts: dict[str, int]) -> float:
        total = 0.0
        for verb, n in verb_counts.items():
            attr = _VERB_TO_WEIGHT.get(verb)
            if attr:
                total += n * getattr(self._weights, attr)
        return round(total, 2)

    def is_declining(self, history: list[float]) -> bool:
        """Declining when the score dropped by >= decline_ratio in each of the last two windows."""
        if len(history) < 3:
            return False
        a, b, c = history[-3], history[-2], history[-1]
        return a > 0 and b <= a * (1 - self._decline_ratio) and c <= b * (1 - self._decline_ratio)
