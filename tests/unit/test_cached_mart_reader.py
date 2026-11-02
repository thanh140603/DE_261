"""CachedMartReader: TTL hits, per-argument keys, failures are not cached."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from edu_platform.contexts.analytics.application.ports import MartUnavailable
from edu_platform.contexts.analytics.infrastructure.cached_mart_reader import CachedMartReader


class Counting:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.fail = False

    def engagement_trend(self, course_id: str, as_of: date | None) -> Any:
        self.calls.append((course_id, as_of))
        if self.fail:
            raise MartUnavailable("trino down")
        return f"trend:{course_id}:{as_of}"


def test_ttl_and_keys() -> None:
    now = [0.0]
    inner = Counting()
    reader = CachedMartReader(inner, ttl_seconds=60, clock=lambda: now[0])  # type: ignore[arg-type]
    assert reader.engagement_trend("c1", None) == "trend:c1:None"
    assert reader.engagement_trend("c1", None) == "trend:c1:None"
    reader.engagement_trend("c1", date(2026, 10, 1))  # different argument -> own entry
    reader.engagement_trend("c2", None)
    assert len(inner.calls) == 3
    now[0] = 61.0
    reader.engagement_trend("c1", None)  # expired
    assert len(inner.calls) == 4


def test_failures_are_not_cached() -> None:
    inner = Counting()
    reader = CachedMartReader(inner)  # type: ignore[arg-type]
    inner.fail = True
    with pytest.raises(MartUnavailable):
        reader.engagement_trend("c1", None)
    inner.fail = False
    assert reader.engagement_trend("c1", None) == "trend:c1:None"
    assert len(inner.calls) == 2
