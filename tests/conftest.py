"""Shared fixtures. Unit tests must not touch I/O - use the in-memory fakes here."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from edu_platform.shared_kernel.domain.event import DomainEvent


class FixedClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class InMemoryEventPublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str | None, DomainEvent]] = []

    def publish(self, events: list[DomainEvent], *, topic: str | None = None) -> None:
        self.published.extend((topic, e) for e in events)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 9, 29, 12, 0, tzinfo=UTC))


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()
