"""Spark adapter: bronze.telemetry_raw -> silver.learning_events with the NormalizeEvents use case.

The same ``NormalizeEvents.normalize_one`` the Flink fast path calls runs here per record
(mapPartitions), so the lakehouse and the real-time branch can never disagree on validation,
schema migration, PII handling or lateness. Used by the batch backfill and by the streaming
silver micro-batches; input rows have the bronze.telemetry_raw columns (view ``_src``).

Record-level failures never fail the batch: they become bronze.telemetry_dlq rows with the
reason. Accepted events are deduplicated on event_id and MERGEd (insert-only) into silver.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from edu_platform.contexts.telemetry.application.normalize_events import NormalizeEvents
from edu_platform.contexts.telemetry.domain.events import LearningEvent, RawEvent, SchemaVersion
from edu_platform.contexts.telemetry.domain.pii import PiiPolicy
from edu_platform.contexts.telemetry.infrastructure.hmac_pseudonymizer import HmacPseudonymizer
from edu_platform.contexts.telemetry.infrastructure.in_memory import (
    InMemoryDeadLetter,
    InMemorySilver,
)
from edu_platform.contexts.telemetry.infrastructure.schema_migrations import ChainedSchemaMigrator
from edu_platform.contexts.telemetry.infrastructure.validator import LearningEventValidator
from edu_platform.shared_kernel.domain import DomainError
from edu_platform.shared_kernel.domain.ids import LearnerId

OUTPUT_DDL = (
    "kind STRING, event_id STRING, learner_pseudonym STRING, course_id STRING, content_id STRING, "
    "session_id STRING, verb STRING, platform STRING, "
    "occurred_at TIMESTAMP, received_at TIMESTAMP, "
    "event_date DATE, video_position_sec INT, is_late BOOLEAN, lateness_sec DOUBLE, "
    "schema_version STRING, extensions STRING, ingest_date DATE, "
    "raw_learner_id STRING, payload STRING, reason STRING"
)

_MERGE_SILVER = """
MERGE INTO silver.learning_events AS t
USING (
  SELECT * FROM (
    SELECT *, row_number() OVER (PARTITION BY event_id ORDER BY received_at) AS rn
    FROM _normalized
  ) WHERE rn = 1
) AS s
ON t.event_date = s.event_date AND t.event_id = s.event_id
WHEN NOT MATCHED THEN INSERT
  (event_id, learner_pseudonym, course_id, content_id, session_id, verb, platform, occurred_at,
   received_at, event_date, video_position_sec, is_late, lateness_sec, schema_version, extensions,
   _ingest_date, _processed_at)
  VALUES (s.event_id, s.learner_pseudonym, s.course_id, s.content_id, s.session_id, s.verb,
          s.platform, s.occurred_at, s.received_at, s.event_date, s.video_position_sec, s.is_late,
          s.lateness_sec, s.schema_version, s.extensions, s.ingest_date, current_timestamp())
"""

_MERGE_DLQ = """
MERGE INTO bronze.telemetry_dlq AS t
USING (
  SELECT DISTINCT event_id, raw_learner_id, payload, reason, received_at, ingest_date FROM _rejected
) AS s
ON t.ingest_date = s.ingest_date AND t.rejected_by = 'spark' AND t.payload = s.payload
WHEN NOT MATCHED THEN INSERT
  (event_id, learner_id, payload, reason, rejected_by, received_at, ingest_date, _landed_at)
  VALUES (s.event_id, s.raw_learner_id, s.payload, s.reason, 'spark', s.received_at, s.ingest_date,
          current_timestamp())
"""


def build_use_case(secret: bytes, key_version: int = 1) -> NormalizeEvents:
    """NormalizeEvents wired with the production adapters (sinks unused: per-record mode)."""
    return NormalizeEvents(
        validator=LearningEventValidator(),
        migrator=ChainedSchemaMigrator(),
        pseudonymizer=HmacPseudonymizer(secret, key_version),
        pii_policy=PiiPolicy(),
        silver=InMemorySilver(),
        dlq=InMemoryDeadLetter(),
    )


def normalize_rows(
    rows: Iterator[Any], secret: bytes, key_version: int = 1
) -> Iterator[tuple[Any, ...]]:
    """Per-partition transform: bronze rows in, tagged ('ok' | 'dlq') output tuples out."""
    use_case = build_use_case(secret, key_version)
    for row in rows:
        received_at = _utc(row["received_at"])
        try:
            payload = json.loads(row["payload"])
            raw = RawEvent(
                event_id=str(row["event_id"] or payload.get("event_id") or ""),
                raw_learner_id=LearnerId(str(row["learner_id"] or payload.get("learner_id") or "")),
                schema_version=SchemaVersion.parse(
                    row["schema_version"] or payload.get("schema_version") or "1.0"
                ),
                payload=payload,
                received_at=received_at,
                source_topic=row["kafka_topic"] or "",
                partition=int(row["kafka_partition"] or 0),
                offset=int(row["kafka_offset"] or 0),
            )
            event = use_case.normalize_one(raw)
        except (DomainError, ValueError, TypeError, KeyError, AttributeError) as exc:
            yield _rejected(row, received_at, f"{type(exc).__name__}: {exc}")
            continue
        yield _accepted(event, row["ingest_date"])


def normalize_to_silver(spark: Any, source_view: str, secret: bytes, key_version: int = 1) -> None:
    """Normalise the rows of ``source_view`` and write silver + DLQ (idempotent)."""
    source = spark.table(source_view)
    tagged = source.rdd.mapPartitions(lambda rows: normalize_rows(rows, secret, key_version))
    frame = spark.createDataFrame(tagged, OUTPUT_DDL).cache()
    try:
        frame.where("kind = 'ok'").createOrReplaceTempView("_normalized")
        frame.where("kind = 'dlq'").createOrReplaceTempView("_rejected")
        spark.sql(_MERGE_SILVER)
        spark.sql(_MERGE_DLQ)
    finally:
        frame.unpersist()


def _accepted(event: LearningEvent, ingest_date: Any) -> tuple[Any, ...]:
    occurred = _utc(event.occurred_at)
    received = _utc(event.received_at)
    return (
        "ok",
        event.event_id,
        event.learner_pseudonym,
        event.course_id,
        event.content_id,
        event.session_id,
        event.verb.value,
        event.platform.value,
        occurred.replace(tzinfo=None),
        received.replace(tzinfo=None),
        occurred.date(),
        event.video_position.second if event.video_position else None,
        event.is_late,
        float(event.lateness_seconds),
        str(event.schema_version),
        json.dumps(event.extensions, sort_keys=True, default=str) if event.extensions else None,
        ingest_date,
        None,
        None,
        None,
    )


def _rejected(row: Any, received_at: datetime, reason: str) -> tuple[Any, ...]:
    return (
        "dlq",
        row["event_id"],
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        received_at.replace(tzinfo=None),
        None,
        None,
        None,
        None,
        None,
        None,
        row["ingest_date"],
        row["learner_id"],
        row["payload"],
        reason[:1000],
    )


def _utc(value: datetime) -> datetime:
    """Spark hands naive datetimes in the session time zone (UTC); make them aware."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
