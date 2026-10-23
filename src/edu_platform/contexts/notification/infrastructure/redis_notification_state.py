"""Redis-backed notification state (BR1): dedup, rate limit, opt-out."""

from __future__ import annotations

import time
import uuid
from typing import Any

from edu_platform.contexts.notification.domain.model import Channel, DedupKey
from edu_platform.platform.storage.redis_client import key


class RedisNotificationState:
    def __init__(self, client: Any) -> None:
        self._client = client

    def seen_before(self, dedup_key: DedupKey, ttl_seconds: int) -> bool:
        """Atomic SET NX: returns True when the key already existed."""
        dedup = key("notif", "dedup", str(dedup_key))
        set_result = self._client.set(dedup, "1", nx=True, ex=ttl_seconds)
        return not bool(set_result)

    def within_rate_limit(self, recipient_id: str, limit: int, window_seconds: int) -> bool:
        """Sliding window via sorted set of epoch-millisecond scores."""
        window = key("notif", "rate", recipient_id)
        now_ms = int(time.time() * 1000)
        self._client.zremrangebyscore(window, 0, now_ms - window_seconds * 1000)
        if self._client.zcard(window) >= limit:
            return False
        self._client.zadd(window, {f"{now_ms}:{uuid.uuid4().hex}": now_ms})
        self._client.expire(window, window_seconds)
        return True

    def opted_out(self, recipient_id: str, channel: Channel) -> bool:
        opt_out = key("notif", "optout", recipient_id)
        return bool(self._client.sismember(opt_out, channel.value))
