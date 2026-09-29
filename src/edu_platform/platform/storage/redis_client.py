"""Redis connection factory for the low-latency serving layer.

Content (TODO):
- Create ``redis.Redis`` from settings.redis_url with connection pooling,
  socket timeouts and retry-on-timeout; optional Redis Cluster toggle.
- Namespaces in use: features (BR2), risk (BR5), notif (BR1 dedup/rate-limit),
  cache-inval (BR8).
"""

from __future__ import annotations

from typing import Any


def key(namespace: str, *parts: str) -> str:
    """Canonical key layout: ``edu:<namespace>:<part>:<part>``."""
    return ":".join(("edu", namespace, *parts))


def create_redis_client(url: str) -> Any:
    raise NotImplementedError  # TODO: redis.Redis.from_url(url, decode_responses=True, ...)
