"""Redis connection factory for the low-latency serving layer.

A single entry point so every service shares timeouts, retry policy and the
decoded-responses convention. Namespaces in use: notif (BR1 dedup/rate-limit),
grading (BR3), risk (BR5), cache-inval (BR8).
"""

from __future__ import annotations

from typing import Any


def key(namespace: str, *parts: str) -> str:
    """Canonical key layout: ``edu:<namespace>:<part>:<part>``."""
    return ":".join(("edu", namespace, *parts))


def create_redis_client(url: str) -> Any:
    """Build a ``redis.Redis`` client with string-decoded responses.

    Imported lazily so services that never touch Redis do not require the
    ``redis`` dependency at import time.
    """
    import redis

    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
        retry_on_timeout=True,
    )
