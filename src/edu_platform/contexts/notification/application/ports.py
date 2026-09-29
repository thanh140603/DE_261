from __future__ import annotations

from typing import Any, Protocol

from edu_platform.contexts.notification.domain.model import (
    Channel,
    DedupKey,
    Notification,
    NotificationContent,
    NotificationRule,
)


class RuleRepository(Protocol):
    def all(self) -> list[NotificationRule]: ...


class AudienceResolver(Protocol):
    """Read model fed by CDC enrollments / staff assignments."""

    def learners_for_course(self, course_id: str) -> list[str]: ...

    def advisor_for_learner(self, learner_id: str) -> str | None: ...


class NotificationStateStore(Protocol):
    """Redis in production: dedup, rate limiting, preferences."""

    def seen_before(self, key: DedupKey, ttl_seconds: int) -> bool: ...

    def within_rate_limit(self, recipient_id: str, limit: int, window_seconds: int) -> bool: ...

    def opted_out(self, recipient_id: str, channel: Channel) -> bool: ...


class TemplateRenderer(Protocol):
    def render(self, template_id: str, payload: dict[str, Any]) -> NotificationContent: ...


class NotificationSender(Protocol):
    channel: Channel

    def send(self, notification: Notification) -> None: ...


class NotificationRepository(Protocol):
    def save(self, notification: Notification) -> None: ...

    def get(self, notification_id: str) -> Notification | None: ...

    def for_recipient(self, recipient_id: str) -> list[Notification]: ...

    def count(self) -> int: ...
