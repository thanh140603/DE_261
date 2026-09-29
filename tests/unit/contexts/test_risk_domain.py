from __future__ import annotations

from datetime import UTC, datetime, timedelta

from edu_platform.contexts.risk.domain.events import DropoutRiskDetected
from edu_platform.contexts.risk.domain.model import (
    LearnerRiskProfile,
    RiskScore,
    RiskSignal,
    SignalKind,
    SlidingWindowPolicy,
)
from edu_platform.shared_kernel.domain.ids import CourseId, LearnerId

T0 = datetime(2026, 9, 29, tzinfo=UTC)
POLICY = SlidingWindowPolicy(alert_threshold=0.7, cooldown=timedelta(days=3))


def _profile() -> LearnerRiskProfile:
    return LearnerRiskProfile(
        id="l1:c1",
        learner_id=LearnerId("l1"),
        course_id=CourseId("c1"),
        signals=[
            RiskSignal(SignalKind.LOGIN_GAP, 0.9, T0),
            RiskSignal(SignalKind.DEADLINE_MISSED, 0.5, T0),
        ],
    )


def test_alert_when_above_threshold() -> None:
    p = _profile()
    p.rescore(RiskScore(0.8, T0), POLICY)
    (event,) = p.pull_events()
    assert isinstance(event, DropoutRiskDetected)
    assert event.top_signals[0] == SignalKind.LOGIN_GAP


def test_no_alert_below_threshold() -> None:
    p = _profile()
    p.rescore(RiskScore(0.3, T0), POLICY)
    assert p.pull_events() == []


def test_cooldown_suppresses_repeat_alert() -> None:
    p = _profile()
    p.rescore(RiskScore(0.9, T0), POLICY)
    p.rescore(RiskScore(0.95, T0 + timedelta(days=1)), POLICY)
    assert len(p.pull_events()) == 1
    p.rescore(RiskScore(0.95, T0 + timedelta(days=4)), POLICY)
    assert len(p.pull_events()) == 1
