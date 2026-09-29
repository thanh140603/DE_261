"""Domain service (BR4): flag test cases / questions with abnormal fail rate."""

from __future__ import annotations

from .model import AnomalyThreshold


class AssessmentAnomalyPolicy:
    def __init__(self, threshold: AnomalyThreshold) -> None:
        self._t = threshold

    def is_anomalous(self, attempts: int, pass_rate: float, median: float) -> bool:
        if attempts < self._t.min_attempts:
            return False
        return (
            pass_rate <= self._t.max_pass_rate
            and (median - pass_rate) >= self._t.min_delta_from_median
        )
