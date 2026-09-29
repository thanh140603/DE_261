"""In-memory notification adapters (tests + demo). Redis/YAML/provider adapters are TODO."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from typing import Any

from edu_platform.contexts.notification.domain.model import (
    Channel,
    DedupKey,
    Notification,
    NotificationContent,
)


class InMemoryNotificationState:
    def __init__(self, now: Any) -> None:  # now: Callable[[], datetime]
        self._now = now
        self._dedup: dict[str, datetime] = {}
        self._sent: dict[str, deque[datetime]] = defaultdict(deque)
        self.opt_outs: dict[str, set[Channel]] = defaultdict(set)

    def seen_before(self, key: DedupKey, ttl_seconds: int) -> bool:
        now = self._now()
        k = str(key)
        first = self._dedup.get(k)
        if first is not None and (now - first).total_seconds() < ttl_seconds:
            return True
        self._dedup[k] = now
        return False

    def within_rate_limit(self, recipient_id: str, limit: int, window_seconds: int) -> bool:
        now = self._now()
        q = self._sent[recipient_id]
        while q and (now - q[0]).total_seconds() > window_seconds:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def opted_out(self, recipient_id: str, channel: Channel) -> bool:
        return channel in self.opt_outs.get(recipient_id, set())


class InMemoryNotificationRepository:
    def __init__(self) -> None:
        self._rows: dict[str, Notification] = {}

    def save(self, notification: Notification) -> None:
        self._rows[notification.id] = notification

    def get(self, notification_id: str) -> Notification | None:
        return self._rows.get(notification_id)

    def for_recipient(self, recipient_id: str) -> list[Notification]:
        rows = [n for n in self._rows.values() if n.recipient_id == recipient_id]
        return sorted(rows, key=lambda n: n.created_at, reverse=True)

    def count(self) -> int:
        return len(self._rows)


class RecordingSender:
    """Channel sender that records deliveries instead of calling a provider."""

    def __init__(self, channel: Channel) -> None:
        self.channel = channel
        self.sent: list[str] = []

    def send(self, notification: Notification) -> None:
        self.sent.append(notification.id)


class StaticAudienceResolver:
    def __init__(self, enrollments: dict[str, list[str]], advisors: dict[str, str]) -> None:
        self._enrollments = enrollments  # course_id -> learner ids
        self._advisors = advisors  # learner_id -> advisor id

    def learners_for_course(self, course_id: str) -> list[str]:
        return list(self._enrollments.get(course_id, []))

    def advisor_for_learner(self, learner_id: str) -> str | None:
        return self._advisors.get(learner_id)


TEMPLATES: dict[str, tuple[str, str]] = {
    "assignment_created": (
        "New assignment: {title}",
        "A new assignment was added to {course_title}.",
    ),
    "deadline_soon": (
        "Due in {hours_to_deadline} h: {title}",
        "Submit {title} before the deadline.",
    ),
    "course_updated": ("{course_title} was updated", "{change_summary}"),
    "submission_feedback": ("Feedback ready: {assignment_title}", "{summary}"),
    "advisor_risk_alert": (
        "{learner_name} may be at risk",
        "Risk score {score:.0%} in {course_title}. Top signals: {signals}.",
    ),
}


class FormatTemplateRenderer:
    def render(self, template_id: str, payload: dict[str, Any]) -> NotificationContent:
        title, body = TEMPLATES.get(template_id, ("{event_type}", "{payload}"))
        safe = defaultdict(lambda: "?", payload)
        safe.setdefault("payload", str(payload))
        try:
            return NotificationContent(
                title.format_map(safe), body.format_map(safe), payload.get("deep_link")
            )
        except (ValueError, KeyError):
            return NotificationContent(title, body, payload.get("deep_link"))
