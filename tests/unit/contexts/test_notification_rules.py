from __future__ import annotations

from datetime import UTC, datetime

from edu_platform.contexts.notification.application.route_event import (
    RouteEvent,
    RouteEventCommand,
)
from edu_platform.contexts.notification.domain.model import (
    Channel,
    NotificationRule,
    Priority,
    RateLimitPolicy,
)
from edu_platform.contexts.notification.domain.rule_engine import RuleEngine, evaluate_condition
from edu_platform.contexts.notification.infrastructure.in_memory import (
    FormatTemplateRenderer,
    InMemoryNotificationRepository,
    InMemoryNotificationState,
    StaticAudienceResolver,
)

RULES = [
    NotificationRule(
        "deadline",
        "lms.deadline_approaching.v1",
        (Channel.PUSH,),
        Priority.HIGH,
        "hours_to_deadline <= 24",
        "deadline_soon",
    ),
    NotificationRule(
        "created",
        "lms.assignment_created.v1",
        (Channel.IN_APP,),
        Priority.NORMAL,
        None,
        "assignment_created",
        audience="course",
    ),
]


def test_condition_language() -> None:
    assert evaluate_condition("hours_to_deadline <= 24", {"hours_to_deadline": 12})
    assert not evaluate_condition("hours_to_deadline <= 24", {"hours_to_deadline": 48})
    assert evaluate_condition("a > 1 and b == 'x'", {"a": 2, "b": "x"})
    assert not evaluate_condition("missing == 1", {})


def test_rule_engine_orders_by_priority_and_filters() -> None:
    engine = RuleEngine(RULES)
    assert [
        r.rule_id for r in engine.match("lms.deadline_approaching.v1", {"hours_to_deadline": 3})
    ] == ["deadline"]
    assert engine.match("lms.deadline_approaching.v1", {"hours_to_deadline": 99}) == []


def _router(publisher, clock) -> tuple[RouteEvent, InMemoryNotificationRepository]:
    repo = InMemoryNotificationRepository()
    state = InMemoryNotificationState(lambda: datetime(2026, 9, 29, 12, tzinfo=UTC))
    audience = StaticAudienceResolver({"c1": ["l1", "l2"]}, {})
    router = RouteEvent(
        RuleEngine(RULES),
        audience,
        state,
        FormatTemplateRenderer(),
        repo,
        RateLimitPolicy(max_per_window=1),
        publisher,
        clock,
    )
    return router, repo


def test_fan_out_dedup_and_rate_limit(publisher, clock) -> None:
    router, repo = _router(publisher, clock)
    first = router.execute(
        RouteEventCommand(
            "e1",
            "lms.assignment_created.v1",
            {"course_id": "c1", "assignment_id": "a1", "title": "T"},
        )
    )
    assert len(first.created) == 2 and repo.count() == 2
    again = router.execute(
        RouteEventCommand(
            "e2",
            "lms.assignment_created.v1",
            {"course_id": "c1", "assignment_id": "a1", "title": "T"},
        )
    )
    assert [r for _, r in again.suppressed] == ["duplicate", "duplicate"]
    other = router.execute(
        RouteEventCommand(
            "e3",
            "lms.assignment_created.v1",
            {"course_id": "c1", "assignment_id": "a2", "title": "T2"},
        )
    )
    assert [r for _, r in other.suppressed] == ["rate_limited", "rate_limited"]
    urgent = router.execute(
        RouteEventCommand(
            "e4",
            "lms.deadline_approaching.v1",
            {"learner_id": "l1", "assignment_id": "a2", "hours_to_deadline": 2, "title": "T2"},
        )
    )
    assert len(urgent.created) == 1, "high priority bypasses the rate limit"
