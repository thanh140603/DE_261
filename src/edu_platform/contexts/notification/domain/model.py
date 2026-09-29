from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from edu_platform.shared_kernel.domain import AggregateRoot, InvariantViolation, ValueObject

from .events import NotificationDispatched, NotificationSuppressed


class Channel(StrEnum):
    PUSH = "push"
    IN_APP = "in_app"
    EMAIL = "email"


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"  # bypasses rate limit (e.g. deadline in < 24 h)


@dataclass(frozen=True)
class DedupKey(ValueObject):
    """Same (recipient, event_type, subject) within ttl is sent at most once."""

    recipient_id: str
    event_type: str
    subject_id: str

    def __str__(self) -> str:
        return f"{self.recipient_id}:{self.event_type}:{self.subject_id}"


@dataclass(frozen=True)
class RateLimitPolicy(ValueObject):
    max_per_window: int = 5
    window: timedelta = timedelta(hours=1)
    dedup_ttl: timedelta = timedelta(hours=24)


@dataclass(frozen=True)
class NotificationRule(ValueObject):
    """Declarative rule evaluated by the RuleEngine (loaded from YAML)."""

    rule_id: str
    event_type: str
    channels: tuple[Channel, ...]
    priority: Priority = Priority.NORMAL
    condition: str | None = None  # e.g. "hours_to_deadline <= 24"
    template_id: str = ""
    audience: str = "learner"  # learner | course | advisor
    enabled: bool = True


@dataclass(frozen=True)
class NotificationContent(ValueObject):
    title: str
    body: str
    deep_link: str | None = None


@dataclass(eq=False, kw_only=True)
class Notification(AggregateRoot[str]):
    recipient_id: str
    dedup_key: DedupKey
    channels: tuple[Channel, ...]
    priority: Priority
    content: NotificationContent
    source_event_id: str
    source_event_type: str
    created_at: datetime
    dispatched: dict[Channel, datetime] = field(default_factory=dict)

    def mark_dispatched(self, channel: Channel, at: datetime) -> None:
        if channel not in self.channels:
            raise InvariantViolation(f"channel {channel} not selected for this notification")
        self.dispatched[channel] = at
        self.record(
            NotificationDispatched(
                aggregate_id=self.id, recipient_id=self.recipient_id, channel=channel
            )
        )

    def suppress(self, reason: str) -> None:
        self.record(
            NotificationSuppressed(
                aggregate_id=self.id, recipient_id=self.recipient_id, reason=reason
            )
        )
