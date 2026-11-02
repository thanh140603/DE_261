"""Debezium ``cdc.lms.public.course_content`` record -> ContentChange.

The connector (infra/debezium/postgres-connector.json) unwraps the envelope
(ExtractNewRecordState, delete.handling.mode=rewrite) and adds ``__op``, ``__ts_ms``,
``__source_lsn``; deletes arrive as the old row image with ``__deleted = "true"``
(REPLICA IDENTITY FULL). JsonConverter may wrap the value as {"schema", "payload"}.
TIMESTAMPTZ columns are ISO strings (ZonedTimestamp); epoch values are accepted too.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from edu_platform.contexts.content.domain.model import ContentType
from edu_platform.contexts.content.domain.sync_policy import ContentChange
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId


def parse_content_change(value: dict[str, Any]) -> ContentChange | None:
    """None for records that carry no row (heartbeats, schema-only messages)."""
    row = value.get("payload", value) if "schema" in value else value
    if not isinstance(row, dict) or not row.get("content_id"):
        return None
    deleted = str(row.get("__deleted", "false")).lower() == "true" or row.get("__op") == "d"
    return ContentChange(
        content_id=ContentId(str(row["content_id"])),
        course_id=CourseId(str(row["course_id"])),
        content_type=ContentType(str(row["content_type"])),
        title=str(row["title"]),
        version=int(row["version"]),
        object_key=str(row["object_key"]),
        changed_at=_timestamp(row.get("updated_at")),
        deleted=deleted,
    )


def _timestamp(value: Any) -> datetime:
    if value is None:
        return datetime.now(tz=UTC)
    if isinstance(value, int | float):  # epoch millis (or micros) when not ZonedTimestamp
        seconds = value / 1_000_000 if value > 10**14 else value / 1000
        return datetime.fromtimestamp(seconds, tz=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
