"""Ports (interfaces) shared across contexts.

Defined as ``typing.Protocol`` so infrastructure adapters do not need to
inherit from anything - structural typing keeps the domain free of
framework imports (Dependency Inversion).
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Protocol, TypeVar

from edu_platform.shared_kernel.domain.aggregate import AggregateRoot
from edu_platform.shared_kernel.domain.event import DomainEvent

TAggregate = TypeVar("TAggregate", bound=AggregateRoot)  # type: ignore[type-arg]
TId_contra = TypeVar("TId_contra", contravariant=True)


class Clock(Protocol):
    """Injectable time source so windowing / SLA logic is testable."""

    def now(self) -> datetime: ...


class EventPublisher(Protocol):
    """Publishes domain events to the event bus (Kafka in production)."""

    def publish(self, events: list[DomainEvent], *, topic: str | None = None) -> None: ...


class Repository(Protocol, Generic[TAggregate, TId_contra]):
    def get(self, aggregate_id: TId_contra) -> TAggregate | None: ...

    def save(self, aggregate: TAggregate) -> None: ...


class UnitOfWork(Protocol):
    """Transaction boundary: persist aggregates and publish their events atomically.

    Implementations should use the transactional outbox pattern when the store
    and the event bus are different systems.
    """

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
