"""Use case: LMS/domain event -> zero or more Notifications (BR1).

1. RuleEngine.match -> rules; none -> nothing.
2. Resolve audience per rule (learner in payload, course fan-out, or advisor).
3. Per recipient x rule: dedup (SET NX), rate limit (HIGH priority bypasses),
   per-channel opt-out; suppressed notifications are recorded with a reason.
4. Render, persist, hand ids back so DispatchNotification can deliver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from edu_platform.contexts.notification.application.ports import (
    AudienceResolver,
    NotificationRepository,
    NotificationStateStore,
    TemplateRenderer,
)
from edu_platform.contexts.notification.domain.model import (
    DedupKey,
    Notification,
    NotificationRule,
    Priority,
    RateLimitPolicy,
)
from edu_platform.contexts.notification.domain.rule_engine import RuleEngine
from edu_platform.shared_kernel.application import Clock, EventPublisher
from edu_platform.shared_kernel.domain.ids import new_id


@dataclass(frozen=True)
class RouteEventCommand:
    event_id: str
    event_type: str
    payload: dict[str, Any]


@dataclass
class RouteEventResult:
    created: list[str] = field(default_factory=list)
    suppressed: list[tuple[str, str]] = field(default_factory=list)  # (recipient, reason)


class RouteEvent:
    def __init__(
        self,
        rule_engine: RuleEngine,
        audience: AudienceResolver,
        state: NotificationStateStore,
        renderer: TemplateRenderer,
        repo: NotificationRepository,
        rate_limit: RateLimitPolicy,
        publisher: EventPublisher,
        clock: Clock,
    ) -> None:
        self._rules = rule_engine
        self._audience = audience
        self._state = state
        self._renderer = renderer
        self._repo = repo
        self._rate_limit = rate_limit
        self._publisher = publisher
        self._clock = clock

    def execute(self, command: RouteEventCommand) -> RouteEventResult:
        result = RouteEventResult()
        now = self._clock.now()
        for rule in self._rules.match(command.event_type, command.payload):
            for recipient in self._recipients(rule, command.payload):
                self._route_one(rule, recipient, command, now, result)
        return result

    def _recipients(self, rule: NotificationRule, payload: dict[str, Any]) -> list[str]:
        if rule.audience == "advisor":
            advisor = self._audience.advisor_for_learner(str(payload.get("learner_id", "")))
            return [advisor] if advisor else []
        if rule.audience == "course" or not payload.get("learner_id"):
            return self._audience.learners_for_course(str(payload.get("course_id", "")))
        return [str(payload["learner_id"])]

    def _route_one(
        self,
        rule: NotificationRule,
        recipient: str,
        command: RouteEventCommand,
        now: datetime,
        result: RouteEventResult,
    ) -> None:
        subject = str(
            command.payload.get("submission_id")
            or command.payload.get("assignment_id")
            or command.payload.get("content_id")
            or command.payload.get("course_id")
            or command.event_id
        )
        key = DedupKey(recipient, command.event_type, subject)
        channels = tuple(c for c in rule.channels if not self._state.opted_out(recipient, c))
        notification = Notification(
            id=new_id(),
            recipient_id=recipient,
            dedup_key=key,
            channels=channels,
            priority=rule.priority,
            content=self._renderer.render(rule.template_id, command.payload),
            source_event_id=command.event_id,
            source_event_type=command.event_type,
            created_at=now,
        )
        reason = None
        if self._state.seen_before(key, int(self._rate_limit.dedup_ttl.total_seconds())):
            reason = "duplicate"
        elif rule.priority is not Priority.HIGH and not self._state.within_rate_limit(
            recipient, self._rate_limit.max_per_window, int(self._rate_limit.window.total_seconds())
        ):
            reason = "rate_limited"
        elif not channels:
            reason = "opted_out"
        if reason:
            notification.suppress(reason)
            self._publisher.publish(notification.pull_events())
            result.suppressed.append((recipient, reason))
            return
        self._repo.save(notification)
        result.created.append(notification.id)
