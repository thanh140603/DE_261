"""Server-Sent Events broadcaster: fan out pipeline activity to browser clients.

``publish`` is safe to call from synchronous handler code (bus consumers) as
long as ``bind_loop`` was called from the running event loop at startup.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any


class Broadcaster:
    def __init__(self, queue_size: int = 200) -> None:
        self._queues: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue_size = queue_size

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, type_: str, payload: dict[str, Any]) -> None:
        if self._loop is None or not self._queues:
            return
        data = json.dumps(
            {"type": type_, "at": datetime.now(tz=UTC).isoformat(), "payload": payload}, default=str
        )
        for q in list(self._queues):
            self._loop.call_soon_threadsafe(_offer, q, data)

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_size)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self._queues.discard(q)


def _offer(q: asyncio.Queue[str], data: str) -> None:
    if q.full():
        q.get_nowait()  # drop oldest for slow clients
    q.put_nowait(data)
