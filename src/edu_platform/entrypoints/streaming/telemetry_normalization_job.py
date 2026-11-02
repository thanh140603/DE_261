"""Spark Structured Streaming: telemetry fast path (BR6 step 2, low latency; ADR 0014).

  telemetry.events.raw.v1 -> NormalizeEvents (validate, migrate schema 1.0 -> 1.1,
  pseudonymise, drop client PII, flag lateness) -> telemetry.learning_events.v1
  rejected records -> telemetry.events.dlq.v1 {"rejected_by", "reason", "payload"}

The same ``normalize_rows`` the lakehouse silver build uses runs in each micro-batch, so
the live path and the warehouse can never disagree on validation or pseudonyms. Kafka
output is at least once (a replayed micro-batch re-sends); consumers dedupe on event_id.
Nothing here writes Delta (ADR 0011): bronze/silver keep landing through Spark separately.
"""

from __future__ import annotations

from typing import Any

from edu_platform.contexts.telemetry.infrastructure.spark_normalizer import (
    OUTPUT_DDL,
    normalize_rows,
)
from edu_platform.platform.messaging.topics import Topic

LEARNING_EVENT_COLUMNS = (
    "event_id, learner_pseudonym, course_id, content_id, session_id, verb, platform, "
    "occurred_at, received_at, event_date, video_position_sec, is_late, lateness_sec, "
    "schema_version"
)
# JSON-escape a string column: to_json(array(x)) = '["..."]' -> strip the brackets
_ESCAPED = "substr(to_json(array({col})), 2, length(to_json(array({col}))) - 2)"
DLQ_VALUE = (
    'concat(\'{"rejected_by":"spark-stream","reason":\', '
    + _ESCAPED.format(col="reason")
    + ", ',\"payload\":', "
    + "CASE WHEN get_json_object(payload, '$') IS NOT NULL THEN payload ELSE "
    + _ESCAPED.format(col="payload")
    + " END, '}')"
)


def raw_source(spark: Any, bootstrap: str, topic: str = Topic.TELEMETRY_RAW.value) -> Any:
    """Kafka records shaped like bronze.telemetry_raw rows (the normaliser's input)."""
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("failOnDataLoss", "false")
        .load()
        .selectExpr(
            "CAST(value AS STRING) AS payload",
            "topic AS kafka_topic",
            "partition AS kafka_partition",
            "offset AS kafka_offset",
            "timestamp AS received_at",
        )
        .where("payload IS NOT NULL")
        .selectExpr(
            "get_json_object(payload, '$.event_id') AS event_id",
            "get_json_object(payload, '$.learner_id') AS learner_id",
            "get_json_object(payload, '$.schema_version') AS schema_version",
            "payload",
            "kafka_topic",
            "kafka_partition",
            "kafka_offset",
            "received_at",
            "to_date(received_at) AS ingest_date",
        )
    )


def normalize_batch(
    spark: Any,
    secret: bytes,
    bootstrap: str,
    *,
    events_topic: str = Topic.LEARNING_EVENTS.value,
    dlq_topic: str = Topic.TELEMETRY_DLQ.value,
) -> Any:
    # One Spark job per micro-batch: the Kafka sink routes each row by its ``topic`` column
    # (separate event / DLQ writes plus an emptiness check tripled the batch time).
    # No emptiness check: Spark does not run micro-batches without new input.
    def apply(batch: Any, batch_id: int) -> None:
        tagged = batch.rdd.mapPartitions(lambda rows: normalize_rows(rows, secret))
        (
            spark.createDataFrame(tagged, OUTPUT_DDL)
            .selectExpr(
                f"CASE WHEN kind = 'ok' THEN '{events_topic}' ELSE '{dlq_topic}' END AS topic",
                "CASE WHEN kind = 'ok' THEN learner_pseudonym ELSE raw_learner_id END AS key",
                f"CASE WHEN kind = 'ok' THEN to_json(struct({LEARNING_EVENT_COLUMNS})) "
                f"ELSE {DLQ_VALUE} END AS value",
            )
            .write.format("kafka")
            .option("kafka.bootstrap.servers", bootstrap)
            .save()
        )

    return apply


def start(
    spark: Any,
    secret: bytes,
    bootstrap: str,
    checkpoint: str,
    *,
    once: bool = False,
    raw_topic: str = Topic.TELEMETRY_RAW.value,
    events_topic: str = Topic.LEARNING_EVENTS.value,
    dlq_topic: str = Topic.TELEMETRY_DLQ.value,
) -> Any:
    writer = (
        raw_source(spark, bootstrap, raw_topic)
        .writeStream.foreachBatch(
            normalize_batch(
                spark, secret, bootstrap, events_topic=events_topic, dlq_topic=dlq_topic
            )
        )
        .option("checkpointLocation", checkpoint)
        .queryName("telemetry-normalize")
    )
    trigger = {"availableNow": True} if once else {"processingTime": "1 second"}
    return writer.trigger(**trigger).start()
