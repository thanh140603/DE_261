"""Spark Structured Streaming: Kafka -> bronze -> silver (ADR 0011: Spark owns Delta writes).

Two hops, each its own checkpointed query so raw capture never waits for transformation:

1. Landing (append-only, exactly-once via checkpoint + Delta transactional sink):
     telemetry.events.raw.v1   -> bronze.telemetry_raw
     telemetry.events.dlq.v1   -> bronze.telemetry_dlq      (Flink fast-path rejections)
     cdc.lms.*  (Debezium)     -> bronze.cdc_events
     business/pipeline topics  -> bronze.domain_events
2. Silver (bronze Delta tables read as streams, foreachBatch): the *same* silver models the
   batch backfill runs (warehouse/models.yaml), applied to each micro-batch; MERGEs are
   idempotent, so a replayed micro-batch is harmless.

  edu stream lakehouse-landing            # continuous (landing every 1 min, silver every 5 min)
  edu stream lakehouse-landing --once     # drain what is available, then stop (availableNow)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import typer

from edu_platform.entrypoints.batch.warehouse_job import build_runner
from edu_platform.platform.config import Settings, get_settings
from edu_platform.platform.logging import get_logger
from edu_platform.platform.messaging.topics import Topic
from edu_platform.platform.warehouse.runner import WarehouseRunner

log = get_logger(__name__)

# Patterns (not fixed lists): tolerate topics that do not exist yet and pick up new ones
# without a redeploy. Anchored - Spark matches patterns anywhere in the topic name, so an
# unanchored "lms\..+" would also capture Debezium's "cdc.lms.public.*".
DOMAIN_TOPIC_PATTERN = r"^(grading|risk|lms|notification|content|features)\..+$"
CDC_TOPIC_PATTERN = r"^cdc\.lms\.public\..+$"
# Debezium JsonConverter may wrap records as {"schema": ..., "payload": ...}.
_UNWRAP = "coalesce(get_json_object({col}, '$.payload'), {col})"


def _kafka(spark: Any, settings: Settings, **subscription: str) -> Any:
    reader = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", settings.kafka.bootstrap_servers)
        .option("startingOffsets", "earliest")
        .option("failOnDataLoss", "false")
    )
    for key, value in subscription.items():
        reader = reader.option(key, value)
    return (
        reader.load()
        .selectExpr(
            "topic",
            "partition AS kafka_partition",
            "offset AS kafka_offset",
            "timestamp AS kafka_timestamp",
            "CAST(key AS STRING) AS k",
            "CAST(value AS STRING) AS v",
        )
        .where("v IS NOT NULL")
    )


def _landing_queries(spark: Any, settings: Settings) -> dict[str, Any]:
    landed = "current_timestamp() AS _landed_at"
    return {
        "bronze.telemetry_raw": _kafka(
            spark, settings, subscribe=Topic.TELEMETRY_RAW.value
        ).selectExpr(
            "get_json_object(v, '$.event_id') AS event_id",
            "get_json_object(v, '$.learner_id') AS learner_id",
            "get_json_object(v, '$.schema_version') AS schema_version",
            "v AS payload",
            "topic AS kafka_topic",
            "kafka_partition",
            "kafka_offset",
            "kafka_timestamp AS received_at",
            "to_date(kafka_timestamp) AS ingest_date",
            landed,
        ),
        "bronze.telemetry_dlq": _kafka(
            spark, settings, subscribe=Topic.TELEMETRY_DLQ.value
        ).selectExpr(
            "get_json_object(v, '$.payload.event_id') AS event_id",
            "get_json_object(v, '$.payload.learner_id') AS learner_id",
            "coalesce(get_json_object(v, '$.payload'), v) AS payload",
            "get_json_object(v, '$.reason') AS reason",
            "'flink' AS rejected_by",
            "kafka_timestamp AS received_at",
            "to_date(kafka_timestamp) AS ingest_date",
            landed,
        ),
        "bronze.cdc_events": _kafka(spark, settings, subscribePattern=CDC_TOPIC_PATTERN)
        .selectExpr(
            "regexp_extract(topic, '([^.]+)$', 1) AS source_table",
            f"{_UNWRAP.format(col='v')} AS after",
            f"{_UNWRAP.format(col='k')} AS record_key",
            "kafka_partition",
            "kafka_offset",
            "kafka_timestamp",
        )
        .selectExpr(
            "source_table",
            "get_json_object(after, '$.__op') AS op",
            "CAST(get_json_object(after, '$.__source_lsn') AS BIGINT) AS lsn",
            "CAST(get_json_object(after, '$.__source_txId') AS BIGINT) AS tx_id",
            "timestamp_millis(CAST(get_json_object(after, '$.__ts_ms') AS BIGINT)) AS source_ts",
            "record_key",
            "after",
            "kafka_partition",
            "kafka_offset",
            "to_date(kafka_timestamp) AS ingest_date",
            landed,
        ),
        "bronze.domain_events": _kafka(
            spark, settings, subscribePattern=DOMAIN_TOPIC_PATTERN
        ).selectExpr(
            "topic",
            "get_json_object(v, '$.event_id') AS event_id",
            "k AS event_key",
            "v AS payload",
            "kafka_partition",
            "kafka_offset",
            "kafka_timestamp",
            "to_date(kafka_timestamp) AS ingest_date",
            landed,
        ),
    }


def _silver_batch(runner: WarehouseRunner, source: str) -> Any:
    specs = [m for m in runner.registry.select(["silver"]) if m.source == source]

    def apply(micro_batch: Any, batch_id: int) -> None:
        if micro_batch.isEmpty():
            return
        ctx = runner.context(datetime.now(tz=UTC).date(), run_id=f"stream-{source}-{batch_id}")
        for spec in specs:
            runner.apply_silver(spec, micro_batch, ctx)
        log.info("silver micro-batch applied", source=source, batch_id=batch_id, models=len(specs))

    return apply


def main(
    once: bool = typer.Option(False, help="availableNow: process available data, then stop"),
) -> None:
    """Run the Kafka -> bronze landing and bronze -> silver streaming queries."""
    settings = get_settings()
    runner = build_runner(settings, "edu-lakehouse-landing")
    spark = runner.spark
    checkpoints = "s3a://checkpoints/lakehouse-landing"

    def trigger(writer: Any, every: str) -> Any:
        return writer.trigger(availableNow=True) if once else writer.trigger(processingTime=every)

    queries = []
    for table, frame in _landing_queries(spark, settings).items():
        writer = (
            frame.writeStream.format("delta")
            .outputMode("append")
            .option("checkpointLocation", f"{checkpoints}/{table}")
            .queryName(f"land:{table}")
        )
        queries.append(trigger(writer, "1 minute").toTable(table))
    if once:  # land everything before transforming it
        for q in queries:
            q.awaitTermination()
        queries = []
    for source in ("bronze.telemetry_raw", "bronze.cdc_events", "bronze.domain_events"):
        writer = (
            spark.readStream.format("delta")
            # bronze is append-only except retention / PII-erasure deletes: skip those commits
            .option("skipChangeCommits", "true")
            .table(source)
            .writeStream.foreachBatch(_silver_batch(runner, source))
            .option("checkpointLocation", f"{checkpoints}/silver-from-{source}")
            .queryName(f"silver:{source}")
        )
        queries.append(trigger(writer, "5 minutes").start())
    if once:
        for q in queries:
            q.awaitTermination()
    else:
        spark.streams.awaitAnyTermination()
