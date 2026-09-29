"""In-process event bus standing in for Kafka.

Keeps a bounded log per topic (for the pipeline UI) and dispatches messages
synchronously to subscribed handlers (the "consumer groups"). Handler failures
are counted and logged, never propagated - like a consumer with a DLQ.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from edu_platform.platform.logging import get_logger
from edu_platform.platform.messaging.topics import Topic
from edu_platform.shared_kernel.domain.event import DomainEvent

log = get_logger(__name__)

# Domain event types whose topic name differs from the event type.
_ROUTES: dict[str, str] = {
    "risk.dropout_risk_detected.v1": Topic.DROPOUT_RISK_ALERT,
    "content.version_published.v1": Topic.CONTENT_UPDATED,
    "content.indexed.v1": Topic.CONTENT_INDEXED,
}

Handler = Callable[["Message"], None]


@dataclass(frozen=True)
class Message:
    topic: str
    key: str
    event_type: str
    payload: dict[str, Any]
    at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class InMemoryEventBus:
    def __init__(self, log_size: int = 500) -> None:
        self._log: dict[str, deque[Message]] = defaultdict(lambda: deque(maxlen=log_size))
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self.counts: dict[str, int] = defaultdict(int)
        self.failures: int = 0
        self.last_at: datetime | None = None

    # -- EventPublisher port --------------------------------------------------
    def publish(self, events: list[DomainEvent], *, topic: str | None = None) -> None:
        for e in events:
            self.emit(
                topic or _ROUTES.get(e.event_type, e.event_type),
                key=e.aggregate_id,
                event_type=e.event_type,
                payload=e.to_payload(),
            )

    # -- raw messages (telemetry, CDC rows, LMS events) -----------------------
    def emit(
        self,
        topic: str,
        *,
        key: str,
        event_type: str,
        payload: dict[str, Any],
        at: datetime | None = None,
    ) -> Message:
        msg = Message(topic=topic, key=key, event_type=event_type, payload=payload)
        if at is not None:  # replayed / backfilled records keep their original ingestion time
            msg = Message(topic=topic, key=key, event_type=event_type, payload=payload, at=at)
        self._log[topic].append(msg)
        self.counts[topic] += 1
        self.last_at = msg.at
        handlers = list(self._handlers.get(topic, []))
        if event_type != topic:
            handlers += self._handlers.get(event_type, [])
        for handler in handlers:
            try:
                handler(msg)
            except Exception:
                self.failures += 1
                log.exception("handler failed", topic=topic, event_type=event_type)
        return msg

    def subscribe(self, topic_or_event_type: str, handler: Handler) -> None:
        self._handlers[topic_or_event_type].append(handler)

    def recent(self, topic: str, limit: int = 20) -> list[Message]:
        return list(self._log.get(topic, []))[-limit:][::-1]

    def topics(self) -> list[dict[str, Any]]:
        return [
            {
                "topic": t,
                "count": self.counts[t],
                "last_at": (self._log[t][-1].at.isoformat() if self._log[t] else None),
            }
            for t in sorted(self.counts)
        ]
