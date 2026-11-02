"""CacheInvalidator adapter on Redis (BR8) + the read-through document cache it guards.

Keys (platform.storage.redis_client.key layout):
  edu:cache:content:<content_id>          cached document payload served to readers (TTL)
  edu:cache:course:<course_id>:outline    cached course outline (built by the LMS readers)
  edu:cache-inval:state:<content_id>      hash {state, at, generation}

``invalidate`` deletes the cached entries and bumps the generation in one transaction, so
a reader that cached under an older generation can detect it lost a race; ``warm`` only
flips the state back once the new version is indexed (readers then refill on miss).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from edu_platform.platform.storage.redis_client import key
from edu_platform.shared_kernel.domain.ids import ContentId


class RedisContentCache:
    def __init__(self, client: Any, ttl_seconds: int = 3600) -> None:
        self._client = client
        self._ttl = ttl_seconds

    @staticmethod
    def _state_key(content_id: str) -> str:
        return key("cache-inval", "state", content_id)

    def invalidate(self, course_id: str, content_id: ContentId) -> None:
        pipe = self._client.pipeline(transaction=True)
        pipe.delete(
            key("cache", "content", content_id), key("cache", "course", course_id, "outline")
        )
        pipe.hset(self._state_key(content_id), mapping={"state": "invalidated", "at": _now()})
        pipe.hincrby(self._state_key(content_id), "generation", 1)
        pipe.execute()

    def warm(self, content_id: ContentId) -> None:
        self._client.hset(self._state_key(content_id), mapping={"state": "warm", "at": _now()})

    def state(self, content_id: ContentId) -> str:
        return str(self._client.hget(self._state_key(content_id), "state") or "warm")

    def generation(self, content_id: str) -> int:
        return int(self._client.hget(self._state_key(content_id), "generation") or 0)

    # --- read-through document cache (API readers) --------------------------------------
    def get_document(self, content_id: str) -> dict[str, Any] | None:
        raw = self._client.get(key("cache", "content", content_id))
        return None if raw is None else dict(json.loads(raw))

    def put_document(self, content_id: str, payload: dict[str, Any], generation: int) -> bool:
        """Cache unless an invalidation happened since the reader saw ``generation``."""
        if self.generation(content_id) != generation:
            return False
        self._client.set(key("cache", "content", content_id), json.dumps(payload), ex=self._ttl)
        return True


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()
