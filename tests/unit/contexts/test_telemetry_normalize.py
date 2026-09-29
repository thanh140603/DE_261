from __future__ import annotations

from datetime import UTC, datetime, timedelta

from edu_platform.contexts.telemetry.application.normalize_events import (
    NormalizeEvents,
    NormalizeEventsCommand,
)
from edu_platform.contexts.telemetry.domain.events import RawEvent, SchemaVersion
from edu_platform.contexts.telemetry.domain.pii import PiiPolicy
from edu_platform.contexts.telemetry.infrastructure.hmac_pseudonymizer import HmacPseudonymizer
from edu_platform.contexts.telemetry.infrastructure.in_memory import (
    InMemoryDeadLetter,
    InMemorySilver,
)
from edu_platform.contexts.telemetry.infrastructure.schema_migrations import (
    ChainedSchemaMigrator,
)
from edu_platform.contexts.telemetry.infrastructure.validator import LearningEventValidator
from edu_platform.shared_kernel.domain.ids import LearnerId

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _raw(
    payload: dict, version: str = "1.1", event_id: str = "e1", received_at: datetime = NOW
) -> RawEvent:
    base = {
        "event_id": event_id,
        "learner_id": "l-001",
        "course_id": "c1",
        "session_id": "s1",
        "verb": "viewed",
        "platform": "web",
        "occurred_at": NOW.isoformat(),
        "email": "a@b.c",
    }
    base.update(payload)
    return RawEvent(
        event_id, LearnerId("l-001"), SchemaVersion.parse(version), base, received_at, "t", 0, 0
    )


def _use_case(silver: InMemorySilver, dlq: InMemoryDeadLetter) -> NormalizeEvents:
    return NormalizeEvents(
        LearningEventValidator(),
        ChainedSchemaMigrator(),
        HmacPseudonymizer(b"k"),
        PiiPolicy(),
        silver,
        dlq,
    )


def test_pseudonymises_and_drops_pii() -> None:
    silver, dlq = InMemorySilver(), InMemoryDeadLetter()
    event = _use_case(silver, dlq).normalize_one(_raw({}))
    assert event.learner_pseudonym != "l-001" and event.learner_pseudonym.startswith("k1_")
    assert "email" not in event.extensions


def test_migrates_schema_1_0() -> None:
    silver, dlq = InMemorySilver(), InMemoryDeadLetter()
    raw = _raw({"ts": NOW.isoformat()}, version="1.0")
    raw.payload.pop("occurred_at")
    raw.payload.pop("platform")
    event = _use_case(silver, dlq).normalize_one(raw)
    assert str(event.schema_version) == "1.1" and event.platform.value == "web"


def test_execute_routes_invalid_late_and_duplicates() -> None:
    silver, dlq = InMemorySilver(), InMemoryDeadLetter()
    late = _raw({}, event_id="late", received_at=NOW + timedelta(minutes=10))
    result = _use_case(silver, dlq).execute(
        NormalizeEventsCommand(
            "run",
            [_raw({}), _raw({}), _raw({"verb": "scrolled"}, event_id="bad"), late],
        )
    )
    assert (result.accepted, result.duplicates, result.rejected, result.late) == (2, 1, 1, 1)
    assert dlq.rows[0].reason.startswith("unknown verb")
