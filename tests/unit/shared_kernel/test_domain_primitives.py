from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pytest

from edu_platform.shared_kernel.domain import (
    AggregateRoot,
    DomainEvent,
    InvariantViolation,
    ValueObject,
)


@dataclass(frozen=True, kw_only=True)
class SomethingHappened(DomainEvent):
    event_type: ClassVar[str] = "test.something_happened.v1"
    detail: str


@dataclass(frozen=True)
class Percent(ValueObject):
    value: float

    def __post_init__(self) -> None:
        if not 0 <= self.value <= 100:
            raise InvariantViolation("out of range")


@dataclass(eq=False)
class Counter(AggregateRoot[str]):
    count: int = 0

    def bump(self) -> None:
        self.count += 1
        self.record(SomethingHappened(aggregate_id=self.id, detail=str(self.count)))


def test_value_objects_compare_by_value() -> None:
    assert Percent(10) == Percent(10)
    assert hash(Percent(10)) == hash(Percent(10))


def test_value_object_invariant() -> None:
    with pytest.raises(InvariantViolation):
        Percent(101)


def test_aggregate_collects_and_drains_events() -> None:
    c = Counter(id="c1")
    c.bump()
    c.bump()
    events = c.pull_events()
    assert [e.detail for e in events] == ["1", "2"]
    assert all(e.aggregate_id == "c1" for e in events)
    assert c.pull_events() == []


def test_entities_compare_by_identity() -> None:
    assert Counter(id="x", count=1) == Counter(id="x", count=2)
    assert Counter(id="x") != Counter(id="y")


def test_event_payload_contains_type_and_iso_time() -> None:
    payload = SomethingHappened(aggregate_id="a", detail="d").to_payload()
    assert payload["event_type"] == "test.something_happened.v1"
    assert payload["occurred_at"].endswith("+00:00")
