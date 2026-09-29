"""In-memory sinks: used by unit tests and by the demo server (single process).

The Delta-backed equivalents live in delta_sinks.py (TODO).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from edu_platform.contexts.telemetry.domain.events import LearningEvent, RawEvent


@dataclass(frozen=True)
class DeadLetter:
    raw: RawEvent
    reason: str
    at: datetime


class InMemoryBronze:
    def __init__(self) -> None:
        self.rows: list[RawEvent] = []

    def append(self, raw: RawEvent) -> None:
        self.rows.append(raw)


class InMemorySilver:
    def __init__(self) -> None:
        self.events: dict[str, LearningEvent] = {}

    def upsert(self, event: LearningEvent) -> bool:
        if event.event_id in self.events:
            return False
        self.events[event.event_id] = event
        return True

    def all(self) -> list[LearningEvent]:
        return list(self.events.values())


class InMemoryDeadLetter:
    def __init__(self) -> None:
        self.rows: list[DeadLetter] = []

    def reject(self, raw: RawEvent, reason: str) -> None:
        self.rows.append(DeadLetter(raw=raw, reason=reason, at=raw.received_at))
