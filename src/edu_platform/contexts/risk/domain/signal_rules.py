"""Domain service: turn upstream facts into RiskSignals (BR5).

Sources: CDC row changes (lesson_progress, submissions, grades), silver
telemetry (login gaps) and grading outcomes (repeated failures). Pure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .model import RiskSignal, SignalKind


class SignalRules:
    def from_row_change(self, table: str, row: dict[str, Any], at: datetime) -> list[RiskSignal]:
        if table == "lesson_progress":
            pct = int(row.get("percent_done", 0))
            # progress moving forward is protective: no signal
            return [] if pct > 0 else [RiskSignal(SignalKind.PROGRESS_STALLED, 0.35, at)]
        if table == "submissions" and row.get("status") == "missed":
            return [RiskSignal(SignalKind.DEADLINE_MISSED, 0.55, at)]
        if table == "grades":
            score = float(row.get("score", 100))
            if score < 50:
                return [RiskSignal(SignalKind.GRADE_DECLINING, 0.45, at)]
        if table == "enrollments" and row.get("status") == "inactive":
            return [RiskSignal(SignalKind.LOGIN_GAP, 0.5, at)]
        return []

    def from_login_gap(self, days_since_login: float, at: datetime) -> list[RiskSignal]:
        if days_since_login < 3:
            return []
        weight = min(0.6, 0.15 + 0.05 * (days_since_login - 3))
        return [RiskSignal(SignalKind.LOGIN_GAP, round(weight, 2), at)]

    def from_grading(self, consecutive_low_pass: int, at: datetime) -> list[RiskSignal]:
        if consecutive_low_pass < 2:
            return []
        return [RiskSignal(SignalKind.REPEATED_FAILURES, min(0.7, 0.25 * consecutive_low_pass), at)]
