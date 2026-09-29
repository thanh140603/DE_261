"""Aggregate root base: collects domain events raised during a transaction.

The application layer pulls events after persisting the aggregate and hands
them to an EventPublisher (outbox pattern recommended for exactly-once).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

from edu_platform.shared_kernel.domain.entity import Entity
from edu_platform.shared_kernel.domain.event import DomainEvent

TId = TypeVar("TId")


@dataclass(eq=False)
class AggregateRoot(Entity[TId]):
    _pending_events: list[DomainEvent] = field(default_factory=list, repr=False, compare=False)
    version: int = 0

    def record(self, event: DomainEvent) -> None:
        self._pending_events.append(event)

    def pull_events(self) -> list[DomainEvent]:
        events, self._pending_events = self._pending_events, []
        return events
