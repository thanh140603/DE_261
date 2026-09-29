"""Ports of the telemetry context (implemented in ./infrastructure)."""

from __future__ import annotations

from typing import Any, Protocol

from edu_platform.contexts.telemetry.domain.events import LearningEvent, RawEvent, SchemaVersion


class BronzeSink(Protocol):
    def append(self, raw: RawEvent) -> None: ...


class SilverSink(Protocol):
    def upsert(self, event: LearningEvent) -> bool:
        """Return True when the event was new, False when deduplicated on event_id."""
        ...


class DeadLetterSink(Protocol):
    def reject(self, raw: RawEvent, reason: str) -> None: ...


class SchemaMigrator(Protocol):
    """Upgrades a payload from ``from_version`` to the current schema version."""

    def migrate(self, payload: dict[str, Any], from_version: SchemaVersion) -> dict[str, Any]: ...


class EventValidator(Protocol):
    def validate(self, payload: dict[str, Any]) -> list[str]:
        """Return a list of validation errors; empty means valid."""
        ...
