"""Spark Structured Streaming: BR2 session-feature branch.

  telemetry.learning_events.v1
    -> per learner, 30-minute inactivity gap (Redis-backed session state)
    -> Redis edu:features:session:<pseudonym> + features.session.v1

Spark 3.5 does not support ``update`` output for ``session_window`` (it only
closes a session after the watermark passes, which would make a 30 s freshness
SLA impossible). This job therefore keeps the tiny session state in Redis and
advances it per micro-batch. ``claim_event`` makes an at-least-once Kafka replay
idempotent, and every Redis write is an absolute snapshot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import typer

from edu_platform.contexts.recommendation.application.compute_session_features import (
    SessionFeaturePolicy,
)
from edu_platform.contexts.recommendation.domain.model import SessionFeatures
from edu_platform.contexts.recommendation.infrastructure.redis_online_store import (
    RedisOnlineFeatureStore,
)
from edu_platform.contexts.telemetry.domain.events import (
    CURRENT_SCHEMA_VERSION,
    LearningEvent,
    Platform,
    Verb,
)
from edu_platform.platform.config import Settings, get_settings
from edu_platform.platform.logging import get_logger
from edu_platform.platform.messaging.kafka_producer import KafkaEventPublisher
from edu_platform.platform.messaging.topics import Topic
from edu_platform.platform.storage.redis_client import create_redis_client
from edu_platform.shared_kernel.domain.ids import CourseId, SessionId

log = get_logger(__name__)
POLICY = SessionFeaturePolicy()


def _event(row: Any) -> LearningEvent | None:
    try:
        occurred_at: datetime = row["occurred_at"]
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        session_id = str(
            row["session_id"] or f"{row['learner_pseudonym']}:{occurred_at.isoformat()}"
        )
        return LearningEvent(
            event_id=str(row["event_id"] or f"{row['partition']}:{row['offset']}"),
            schema_version=CURRENT_SCHEMA_VERSION,
            learner_pseudonym=str(row["learner_pseudonym"]),
            course_id=CourseId(str(row["course_id"] or "")),
            content_id=None,
            session_id=SessionId(session_id),
            verb=Verb(str(row["verb"])),
            platform=Platform.WEB,
            occurred_at=occurred_at,
            received_at=occurred_at,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _publish(publisher: KafkaEventPublisher, features: SessionFeatures) -> None:
    publisher.publish_raw(
        Topic.SESSION_FEATURES.value,
        key=features.learner_pseudonym,
        payload={
            "event_type": Topic.SESSION_FEATURES.value,
            "learner_pseudonym": features.learner_pseudonym,
            "session_id": features.session_id,
            "active_minutes": features.active_minutes,
            "events_in_session": features.events_in_session,
            "last_verbs": list(features.last_verbs),
            "current_course_id": features.current_course_id,
            "struggle_score": features.struggle_score,
            "updated_at": features.updated_at.isoformat(),
            "started_at": features.started_at.isoformat() if features.started_at else None,
        },
    )


def write_batch(
    batch: Any,
    store: RedisOnlineFeatureStore,
    publisher: KafkaEventPublisher,
) -> None:
    by_learner: dict[str, list[Any]] = {}
    for row in batch.collect():
        by_learner.setdefault(str(row["learner_pseudonym"]), []).append(row)

    for pseudonym, rows in by_learner.items():
        previous = store.get_session(pseudonym)
        for raw in sorted(rows, key=lambda row: (row["occurred_at"], row["offset"])):
            event = _event(raw)
            if event is None:
                continue
            if not store.claim_event(event.event_id):
                continue  # Kafka re-delivery of a batch we already applied
            previous = POLICY.advance(previous, event)
            store.put_session(previous)
            _publish(publisher, previous)
    publisher.flush()


def start(
    spark: Any,
    settings: Settings,
    store: RedisOnlineFeatureStore,
    checkpoint: str,
    *,
    once: bool = False,
) -> Any:
    publisher = KafkaEventPublisher(
        settings.kafka.bootstrap_servers, client_id="edu-session-features"
    )
    source = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", settings.kafka.bootstrap_servers)
        .option("subscribe", Topic.LEARNING_EVENTS.value)
        .option("startingOffsets", "earliest")
        .option("failOnDataLoss", "false")
        .load()
        .selectExpr(
            "CAST(value AS STRING) AS raw",
            "partition",
            "offset",
            "get_json_object(CAST(value AS STRING), '$.event_id') AS event_id",
            "get_json_object(CAST(value AS STRING), '$.learner_pseudonym') AS learner_pseudonym",
            "get_json_object(CAST(value AS STRING), '$.session_id') AS session_id",
            "get_json_object(CAST(value AS STRING), '$.course_id') AS course_id",
            "get_json_object(CAST(value AS STRING), '$.verb') AS verb",
            "to_timestamp(get_json_object(CAST(value AS STRING), '$.occurred_at')) AS occurred_at",
        )
        .where("learner_pseudonym IS NOT NULL AND occurred_at IS NOT NULL")
    )

    writer = (
        source.writeStream.foreachBatch(
            lambda batch, _batch_id: write_batch(batch, store, publisher)
        )
        .option("checkpointLocation", checkpoint)
        .queryName("session-features")
    )
    trigger = {"availableNow": True} if once else {"processingTime": "30 seconds"}
    return writer.trigger(**trigger).start()


def main(
    once: bool = typer.Option(False, help="availableNow: process available data, then stop"),
) -> None:
    from edu_platform.platform.batch.spark_session import build_spark

    settings = get_settings()
    spark = build_spark("edu-session-features", settings)
    store = RedisOnlineFeatureStore(create_redis_client(settings.redis_url))
    query = start(
        spark,
        settings,
        store,
        settings.stream_checkpoint_root.rstrip("/") + "/session-features",
        once=once,
    )
    log.info("session features query started", once=once)
    query.awaitTermination()


if __name__ == "__main__":
    typer.run(main)
