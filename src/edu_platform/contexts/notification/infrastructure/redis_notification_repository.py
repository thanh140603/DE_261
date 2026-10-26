"""Redis-backed notification repository (BR1).

Items are stored once under ``edu:notif:item:<id>`` and an id list per recipient
under ``edu:notif:inbox:<recipient>`` so reads are index lookups, newest first.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from edu_platform.contexts.notification.domain.model import (
    Channel,
    DedupKey,
    Notification,
    NotificationContent,
    Priority,
)
from edu_platform.platform.storage.redis_client import key

_ITEM_TTL_SECONDS = 30 * 24 * 3600
_INBOX_MAX = 200


def _to_dict(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "recipient_id": notification.recipient_id,
        "dedup_key": {
            "recipient_id": notification.dedup_key.recipient_id,
            "event_type": notification.dedup_key.event_type,
            "subject_id": notification.dedup_key.subject_id,
        },
        "channels": [channel.value for channel in notification.channels],
        "priority": notification.priority.value,
        "content": {
            "title": notification.content.title,
            "body": notification.content.body,
            "deep_link": notification.content.deep_link,
        },
        "source_event_id": notification.source_event_id,
        "source_event_type": notification.source_event_type,
        "created_at": notification.created_at.isoformat(),
        "dispatched": {c.value: ts.isoformat() for c, ts in notification.dispatched.items()},
    }


def _from_dict(raw: dict[str, Any]) -> Notification:
    dedup = raw["dedup_key"]
    return Notification(
        id=raw["id"],
        recipient_id=raw["recipient_id"],
        dedup_key=DedupKey(dedup["recipient_id"], dedup["event_type"], dedup["subject_id"]),
        channels=tuple(Channel(c) for c in raw["channels"]),
        priority=Priority(raw["priority"]),
        content=NotificationContent(
            raw["content"]["title"], raw["content"]["body"], raw["content"].get("deep_link")
        ),
        source_event_id=raw["source_event_id"],
        source_event_type=raw["source_event_type"],
        created_at=datetime.fromisoformat(raw["created_at"]),
        dispatched={Channel(c): datetime.fromisoformat(ts) for c, ts in raw["dispatched"].items()},
    )


class RedisNotificationRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    def save(self, notification: Notification) -> None:
        self._client.set(
            key("notif", "item", notification.id),
            json.dumps(_to_dict(notification)),
            ex=_ITEM_TTL_SECONDS,
        )
        inbox = key("notif", "inbox", notification.recipient_id)
        self._client.lpush(inbox, notification.id)
        self._client.ltrim(inbox, 0, _INBOX_MAX - 1)
        self._client.incr(key("notif", "count"))

    def get(self, notification_id: str) -> Notification | None:
        raw = self._client.get(key("notif", "item", notification_id))
        return _from_dict(json.loads(raw)) if raw is not None else None

    def for_recipient(self, recipient_id: str) -> list[Notification]:
        ids = self._client.lrange(key("notif", "inbox", recipient_id), 0, -1)
        rows = [self.get(str(i)) for i in ids]
        return [n for n in rows if n is not None]

    def count(self) -> int:
        value = self._client.get(key("notif", "count"))
        return int(value) if value is not None else 0
