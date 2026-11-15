"""Redis-backed notification repository (BR1).

Items are stored once under ``edu:notif:item:<id>`` and an id list per recipient
under ``edu:notif:inbox:<recipient>`` so reads are index lookups, newest first.
A per-recipient sorted set (``edu:notif:time:<recipient>``) mirrors the list
with ``created_at`` as score, so the API can serve the newest page and an
unread count without loading the whole inbox.
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
_TIMELINE_TTL_SECONDS = _ITEM_TTL_SECONDS


def _inbox_key(recipient_id: str) -> str:
    return key("notif", "inbox", recipient_id)


def _timeline_key(recipient_id: str) -> str:
    return key("notif", "time", recipient_id)


def _score(created_at: datetime) -> int:
    """Microsecond epoch as the sorted-set score; exact for any realistic date."""
    return int(created_at.timestamp() * 1_000_000)


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

    def _get_many(self, ids: list[str]) -> list[Notification]:
        """Fetch items in one round trip; the inbox order is preserved."""
        if not ids:
            return []
        raws = self._client.mget([key("notif", "item", notification_id) for notification_id in ids])
        return [_from_dict(json.loads(raw)) for raw in raws if raw is not None]

    def _index_timeline(self, recipient_id: str, rows: list[Notification]) -> None:
        if not rows:
            return
        timeline = _timeline_key(recipient_id)
        self._client.zadd(timeline, {n.id: _score(n.created_at) for n in rows})
        self._client.zremrangebyrank(timeline, 0, -(_INBOX_MAX + 1))
        self._client.expire(timeline, _TIMELINE_TTL_SECONDS)

    def _ensure_timeline(self, recipient_id: str) -> None:
        """Backfill the sorted set for inboxes written before it existed."""
        timeline = _timeline_key(recipient_id)
        if self._client.zcard(timeline):
            return
        ids = self._client.lrange(_inbox_key(recipient_id), 0, -1)
        self._index_timeline(recipient_id, self._get_many([str(i) for i in ids]))

    def save(self, notification: Notification) -> None:
        """Create-or-update one notification.

        ``RouteEvent`` saves the new notification and ``DispatchNotification``
        saves it again after marking the channels dispatched. The repository is
        therefore idempotent by notification id: only the first save appends to
        the inbox and increments the counter; later saves update the item so the
        dispatched timestamps survive.
        """
        item_key = key("notif", "item", notification.id)
        payload = json.dumps(_to_dict(notification))
        created = self._client.set(item_key, payload, ex=_ITEM_TTL_SECONDS, nx=True)
        if created:
            inbox = _inbox_key(notification.recipient_id)
            self._client.lpush(inbox, notification.id)
            self._client.ltrim(inbox, 0, _INBOX_MAX - 1)
            # First write after a deploy: index the pre-existing inbox before adding this item,
            # otherwise the sorted set would start with one member and hide the old history.
            self._ensure_timeline(notification.recipient_id)
            self._index_timeline(notification.recipient_id, [notification])
            self._client.incr(key("notif", "count"))
            event_index = key("notif", "event", notification.source_event_id)
            self._client.sadd(event_index, notification.id)
            self._client.expire(event_index, _ITEM_TTL_SECONDS)
        else:
            self._client.set(item_key, payload, ex=_ITEM_TTL_SECONDS)

    def get(self, notification_id: str) -> Notification | None:
        raw = self._client.get(key("notif", "item", notification_id))
        return _from_dict(json.loads(raw)) if raw is not None else None

    def for_recipient(self, recipient_id: str, limit: int | None = None) -> list[Notification]:
        """Newest-first inbox; ``limit`` reads only the newest page."""
        if limit is None:
            ids = self._client.lrange(_inbox_key(recipient_id), 0, -1)
        else:
            if limit <= 0:
                return []
            self._ensure_timeline(recipient_id)
            ids = self._client.zrevrange(_timeline_key(recipient_id), 0, limit - 1)
        return self._get_many([str(i) for i in ids])

    def count_since(self, recipient_id: str, since: datetime) -> int:
        """Unread count without loading items: O(log n) on the timeline."""
        self._ensure_timeline(recipient_id)
        return int(self._client.zcount(_timeline_key(recipient_id), f"({_score(since)}", "+inf"))

    def for_source_event(self, event_id: str) -> list[Notification]:
        """Notifications created by one upstream event (used by the simulate endpoint)."""
        ids = self._client.smembers(key("notif", "event", event_id))
        return self._get_many([str(i) for i in ids])

    def count(self) -> int:
        value = self._client.get(key("notif", "count"))
        return int(value) if value is not None else 0
