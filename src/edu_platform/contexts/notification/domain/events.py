from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from edu_platform.shared_kernel.domain import DomainEvent


@dataclass(frozen=True, kw_only=True)
class NotificationDispatched(DomainEvent):
    event_type: ClassVar[str] = "notification.dispatched.v1"
    recipient_id: str
    channel: str


@dataclass(frozen=True, kw_only=True)
class NotificationSuppressed(DomainEvent):
    event_type: ClassVar[str] = "notification.suppressed.v1"
    recipient_id: str
    reason: str  # "duplicate" | "rate_limited" | "no_matching_rule" | "opted_out"
