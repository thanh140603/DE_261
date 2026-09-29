"""Use case: bronze -> silver normalisation (BR6 step 2).

Engine-agnostic: ``normalize_one`` is a pure per-record transform that a Flink
map function, a Spark mapPartitions or the in-process demo bus can all call.
Per record:
1. Migrate schema_version -> CURRENT_SCHEMA_VERSION (SchemaMigrator).
2. Validate payload (EventValidator); invalid -> DeadLetterSink with reason.
3. Apply PiiPolicy: drop listed fields, pseudonymise identifiers.
4. Map to LearningEvent (closed Verb vocabulary; unknown verb -> DLQ).
5. Flag lateness; deduplicate on event_id (offline mobile clients re-send).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from edu_platform.contexts.telemetry.application.ports import (
    DeadLetterSink,
    EventValidator,
    SchemaMigrator,
    SilverSink,
)
from edu_platform.contexts.telemetry.domain.events import (
    CURRENT_SCHEMA_VERSION,
    LatenessPolicy,
    LearningEvent,
    Platform,
    RawEvent,
    VideoPosition,
)
from edu_platform.contexts.telemetry.domain.events import Verb as Verb
from edu_platform.contexts.telemetry.domain.pii import PiiPolicy, Pseudonymizer
from edu_platform.shared_kernel.domain import DomainError
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId, SessionId


class RejectedEvent(DomainError):
    """Raised by normalize_one when a record cannot become a silver event."""


@dataclass(frozen=True)
class NormalizeEventsCommand:
    run_id: str
    events: Iterable[RawEvent]


@dataclass
class NormalizeResult:
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    late: int = 0
    migrated: int = 0
    reasons: list[str] = field(default_factory=list)


class NormalizeEvents:
    def __init__(
        self,
        validator: EventValidator,
        migrator: SchemaMigrator,
        pseudonymizer: Pseudonymizer,
        pii_policy: PiiPolicy,
        silver: SilverSink,
        dlq: DeadLetterSink,
        lateness: LatenessPolicy | None = None,
    ) -> None:
        self._validator = validator
        self._migrator = migrator
        self._pseudonymizer = pseudonymizer
        self._pii_policy = pii_policy
        self._silver = silver
        self._dlq = dlq
        self._lateness = lateness or LatenessPolicy()

    def normalize_one(self, raw: RawEvent) -> LearningEvent:
        payload = dict(raw.payload)
        if raw.schema_version < CURRENT_SCHEMA_VERSION:
            payload = self._migrator.migrate(payload, raw.schema_version)
        errors = self._validator.validate(payload)
        if errors:
            raise RejectedEvent("; ".join(errors))
        payload = self._pii_policy.apply(payload, self._pseudonymizer)
        try:
            verb = Verb(payload["verb"])
        except ValueError as exc:
            raise RejectedEvent(f"unknown verb {payload.get('verb')!r}") from exc
        occurred_at = _parse_ts(payload["occurred_at"])
        position = payload.get("video_position_sec")
        return LearningEvent(
            event_id=raw.event_id,
            schema_version=CURRENT_SCHEMA_VERSION,
            learner_pseudonym=payload["learner_id"],
            course_id=CourseId(payload["course_id"]),
            content_id=ContentId(payload["content_id"]) if payload.get("content_id") else None,
            session_id=SessionId(payload["session_id"]),
            verb=verb,
            platform=Platform(payload.get("platform", "web")),
            occurred_at=occurred_at,
            received_at=raw.received_at,
            video_position=VideoPosition(int(position)) if position is not None else None,
            is_late=self._lateness.is_late(occurred_at, raw.received_at),
            extensions=dict(payload.get("extensions") or {}),
        )

    def execute(self, command: NormalizeEventsCommand) -> NormalizeResult:
        result = NormalizeResult()
        for raw in command.events:
            if raw.schema_version < CURRENT_SCHEMA_VERSION:
                result.migrated += 1
            try:
                event = self.normalize_one(raw)
            except DomainError as exc:
                self._dlq.reject(raw, str(exc))
                result.rejected += 1
                result.reasons.append(str(exc))
                continue
            if not self._silver.upsert(event):
                result.duplicates += 1
                continue
            result.accepted += 1
            if event.is_late:
                result.late += 1
        return result


def _parse_ts(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RejectedEvent(f"invalid occurred_at {value!r}") from exc
