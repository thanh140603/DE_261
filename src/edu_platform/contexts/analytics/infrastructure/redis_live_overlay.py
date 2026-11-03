"""Live BR7/BR8 overlays in Redis: written by the streaming job, read by the API.

Keys (platform.storage.redis_client.key layout), all per UTC event day, TTL 3 days:
  edu:live:heatmap:<content_id>:<day>      hash  <second> -> "play,pause,seek,learners"
  edu:live:engagement:<course_id>:<day>    hash  <learner pseudonym> -> score
  edu:live:status                          hash  heatmap_at / engagement_at (last write, ISO)

Every write is an *absolute* value (the streaming aggregation's current total for that key),
so a micro-batch replayed after a restart rewrites the same numbers instead of adding them.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from edu_platform.contexts.analytics.application.ports import (
    LiveEngagement,
    LiveHeatmap,
    LiveSecond,
)
from edu_platform.platform.storage.redis_client import key

TTL_SECONDS = 3 * 24 * 3600
_STATUS = key("live", "status")

HeatmapRow = tuple[date, str, int, int, int, int, int]  # day, content, second, p, pa, s, learners
EngagementRow = tuple[date, str, str, float]  # day, course, pseudonym, score


def _heatmap_key(content_id: str, day: date) -> str:
    return key("live", "heatmap", content_id, day.isoformat())


def _engagement_key(course_id: str, day: date) -> str:
    return key("live", "engagement", course_id, day.isoformat())


class RedisLiveOverlay:
    def __init__(self, client: Any) -> None:
        self._client = client

    # --- writer (streaming job, foreachBatch) ---------------------------------------------
    def write_heatmap(self, rows: Iterable[HeatmapRow]) -> int:
        pipe = self._client.pipeline(transaction=False)
        keys: set[str] = set()
        n = 0
        for day, content_id, second, play, pause, seek, learners in rows:
            k = _heatmap_key(content_id, day)
            pipe.hset(k, str(second), f"{play},{pause},{seek},{learners}")
            keys.add(k)
            n += 1
        return self._finish(pipe, keys, "heatmap_at", n)

    def write_engagement(self, rows: Iterable[EngagementRow]) -> int:
        pipe = self._client.pipeline(transaction=False)
        keys: set[str] = set()
        n = 0
        for day, course_id, pseudonym, score in rows:
            k = _engagement_key(course_id, day)
            pipe.hset(k, pseudonym, f"{round(score, 2)}")
            keys.add(k)
            n += 1
        return self._finish(pipe, keys, "engagement_at", n)

    def _finish(self, pipe: Any, keys: set[str], status_field: str, n: int) -> int:
        for k in keys:
            pipe.expire(k, TTL_SECONDS)
        pipe.hset(_STATUS, status_field, datetime.now(tz=UTC).isoformat())
        pipe.execute()
        return n

    # --- reader (API) ---------------------------------------------------------------------
    def _status(self, field: str) -> datetime | None:
        raw = self._client.hget(_STATUS, field)
        return None if raw is None else datetime.fromisoformat(str(raw))

    def heatmap(self, content_id: str, days: list[date]) -> LiveHeatmap:
        totals: dict[int, list[int]] = {}
        contributing: list[date] = []
        for day in days:
            values = self._client.hgetall(_heatmap_key(content_id, day))
            if not values:
                continue
            contributing.append(day)
            for second, packed in values.items():
                parts = [int(x) for x in str(packed).split(",")]
                acc = totals.setdefault(int(second), [0, 0, 0, 0])
                acc[0] += parts[0]
                acc[1] += parts[1]
                acc[2] += parts[2]
                acc[3] = max(acc[3], parts[3])  # distinct learners are not additive over days
        return LiveHeatmap(
            content_id=content_id,
            days=contributing,
            updated_at=self._status("heatmap_at"),
            seconds=[LiveSecond(s, *totals[s]) for s in sorted(totals)],
        )

    def engagement(self, course_id: str, day: date) -> LiveEngagement:
        values = self._client.hgetall(_engagement_key(course_id, day))
        return LiveEngagement(
            course_id=course_id,
            day=day,
            updated_at=self._status("engagement_at"),
            scores={str(p): float(s) for p, s in values.items()},
        )
