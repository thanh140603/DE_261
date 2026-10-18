"""The Spark telemetry adapter, exercised on plain rows (no Spark session needed)."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from edu_platform.contexts.telemetry.infrastructure.spark_normalizer import normalize_rows

SECRET = b"test-secret"


def _row(payload: dict[str, Any] | str, **over: Any) -> dict[str, Any]:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    base = {
        "event_id": None if isinstance(payload, str) else payload.get("event_id"),
        "learner_id": "l-001",
        "schema_version": None if isinstance(payload, str) else payload.get("schema_version"),
        "payload": raw,
        "kafka_topic": "telemetry.events.raw.v1",
        "kafka_partition": 0,
        "kafka_offset": 1,
        "received_at": datetime(2026, 10, 17, 9, 0, 30),  # naive UTC, as Spark returns it
        "ingest_date": date(2026, 10, 17),
    }
    return base | over


def _event(**over: Any) -> dict[str, Any]:
    return {
        "event_id": "e1",
        "schema_version": "1.1",
        "learner_id": "l-001",
        "course_id": "c-sql-101",
        "content_id": "v-sql-joins",
        "session_id": "s1",
        "verb": "played",
        "platform": "android",
        "occurred_at": "2026-10-17T09:00:00Z",
        "video_position_sec": 42,
        "email": "leak@example.edu",
    } | over


def test_accepted_event_is_pseudonymised_and_typed() -> None:
    [out] = list(normalize_rows(iter([_row(_event())]), SECRET))
    assert out[0] == "ok"
    assert out[2].startswith("k1_") and "l-001" not in json.dumps(out, default=str)
    assert out[6:8] == ("played", "android")
    assert out[10] == date(2026, 10, 17) and out[11] == 42 and out[12] is False
    assert "leak@example.edu" not in json.dumps(out, default=str)


def test_schema_1_0_payload_is_migrated() -> None:
    legacy = _event(schema_version="1.0")
    legacy["ts"] = legacy.pop("occurred_at")
    legacy.pop("platform")
    [out] = list(normalize_rows(iter([_row(legacy)]), SECRET))
    assert out[0] == "ok" and out[7] == "web" and out[14] == "1.1"


def test_late_event_is_flagged_not_dropped() -> None:
    [out] = list(
        normalize_rows(iter([_row(_event(), received_at=datetime(2026, 10, 19, 9, 0))]), SECRET)
    )
    assert out[0] == "ok" and out[12] is True and out[13] == 2 * 86400


def test_invalid_records_go_to_dlq_with_reason() -> None:
    rows = [
        _row(_event(verb="teleported")),
        _row("{not json"),
        _row(_event(occurred_at="2026-10-17T09:00:00")),  # no offset: ambiguous instant
    ]
    outs = list(normalize_rows(iter(rows), SECRET))
    assert [o[0] for o in outs] == ["dlq", "dlq", "dlq"]
    assert "teleported" in outs[0][19]
    assert all(o[17] == "l-001" for o in outs), "DLQ keeps the raw id (bronze only)"
