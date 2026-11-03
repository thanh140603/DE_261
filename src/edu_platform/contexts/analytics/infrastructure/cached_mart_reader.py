"""AnalyticsMartReader decorator: short TTL cache in front of the SQL warehouse.

The marts change once per warehouse run (daily), while dashboards poll every few seconds
for the live overlay. Without a cache every poll became a Trino query (thousands per hour
from one open dashboard), which is what pushed the single-node Trino over its memory
limit. Entries expire after ``ttl_seconds``; failures are never cached.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

from edu_platform.contexts.analytics.application.ports import (
    AnalyticsMartReader,
    EngagementTrendSnapshot,
    NamedRef,
    OrgProgressSnapshot,
    VideoHeatmapSnapshot,
    VideoVersion,
)

T = TypeVar("T")


class CachedMartReader:
    def __init__(
        self,
        inner: AnalyticsMartReader,
        ttl_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = 2048,
    ) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._clock = clock
        self._max = max_entries
        self._entries: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def _cached(self, key: tuple[Any, ...], load: Callable[[], T]) -> T:
        now = self._clock()
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]  # type: ignore[no-any-return]
        value = load()  # outside the lock: a slow query does not block other keys
        with self._lock:
            if len(self._entries) >= self._max:
                self._entries = {k: v for k, v in self._entries.items() if v[0] > now}
            self._entries[key] = (now + self._ttl, value)
        return value

    def organisations(self, ids: list[str]) -> list[NamedRef]:
        return self._cached(("orgs", tuple(ids)), lambda: self._inner.organisations(ids))

    def courses(self, ids: list[str]) -> list[NamedRef]:
        return self._cached(("courses", tuple(ids)), lambda: self._inner.courses(ids))

    def org_progress(self, organisation_id: str, as_of: date | None) -> OrgProgressSnapshot | None:
        return self._cached(
            ("org", organisation_id, as_of),
            lambda: self._inner.org_progress(organisation_id, as_of),
        )

    def course_videos(self, course_id: str) -> list[VideoVersion]:
        return self._cached(("videos", course_id), lambda: self._inner.course_videos(course_id))

    def video(self, content_id: str) -> list[VideoVersion]:
        return self._cached(("video", content_id), lambda: self._inner.video(content_id))

    def video_heatmap(self, content_id: str, version: int | None) -> VideoHeatmapSnapshot | None:
        return self._cached(
            ("heatmap", content_id, version),
            lambda: self._inner.video_heatmap(content_id, version),
        )

    def engagement_trend(
        self, course_id: str, as_of: date | None
    ) -> EngagementTrendSnapshot | None:
        return self._cached(
            ("engagement", course_id, as_of),
            lambda: self._inner.engagement_trend(course_id, as_of),
        )
