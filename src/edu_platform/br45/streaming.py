"""Spark Structured Streaming: signed CDC events -> real event-time hopping windows."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from .config import settings
from .contracts import timestamp
from .db import connect, state
from .risk import refresh


def run() -> None:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as sf
    from pyspark.sql.types import IntegerType, StringType, StructField, StructType

    cfg = settings()
    spark = (
        SparkSession.builder.appName("BR5-event-time-risk")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    schema = StructType(
        [
            StructField(k, StringType(), False)
            for k in ("event_id", "student_id", "course_id", "event_time", "kind")
        ]
        + [StructField("delta", IntegerType(), False)]
    )
    source = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", cfg.kafka)
        .option("subscribe", cfg.activity_topic)
        .option("startingOffsets", "earliest")
        .option("maxOffsetsPerTrigger", 50000)
        .load()
    )
    events = (
        source.select(sf.from_json(sf.col("value").cast("string"), schema).alias("event"))
        .select("event.*")
        .withColumn("event_time", sf.to_timestamp("event_time"))
    )
    # Re-published outbox messages have the same id and event time. Retractions have distinct ids.
    windows = (
        events.withWatermark("event_time", f"{cfg.lateness_days} days")
        .dropDuplicatesWithinWatermark(["event_id"])
        .groupBy(
            "student_id",
            "course_id",
            sf.window("event_time", "7 days", f"{cfg.slide_seconds} seconds"),
        )
        .agg(sf.sum("delta").alias("activity_count"))
    )

    def write_batch(batch: Any, batch_id: int) -> None:
        # One transaction: absolute window upserts and diagnostics.
        # foreachBatch can replay; totals replace prior values and alert keys are stable.
        with connect() as conn:
            count = 0
            for r in batch.toLocalIterator():
                conn.execute(
                    (
                        "INSERT INTO analytics.activity_windows(student_id,course_id,"
                        "window_start,win"
                        "dow_end,activity_count) VALUES(%s,%s,%s,%s,%s) ON "
                        "CONFLICT(student_id,course_id,window_end) DO UPDATE SET "
                        "activity_count=excluded.activity_count,computed_at=now()"
                    ),
                    (
                        r.student_id,
                        r.course_id,
                        r.window.start.replace(tzinfo=UTC),
                        r.window.end.replace(tzinfo=UTC),
                        r.activity_count,
                    ),
                )
                count += 1
            state(
                conn,
                "stream",
                {
                    "batch_id": batch_id,
                    "window_rows": count,
                    "last_success_at": datetime.now(UTC).isoformat(),
                    "checkpoint": cfg.checkpoint,
                },
            )

    query = (
        windows.writeStream.outputMode("update")
        .foreachBatch(write_batch)
        .option("checkpointLocation", cfg.checkpoint)
        .trigger(processingTime="5 seconds")
        .start()
    )
    try:
        while query.isActive:
            query.awaitTermination(5)
            progress = query.lastProgress
            if progress:
                with connect() as conn:
                    state(conn, "spark_progress", progress)
                    mark = progress.get("eventTime", {}).get("watermark")
                    if mark and timestamp(mark).year > 1970:
                        state(conn, "stream_watermark", mark)
                    # Never score partial features while the transactional outbox is ahead.
                    published = state(conn, "published_offsets") or {}
                    end_offsets = progress.get("sources", [{}])[0].get("endOffset", {})
                    if isinstance(end_offsets, str):
                        end_offsets = json.loads(end_offsets)
                    consumed = end_offsets.get(cfg.activity_topic, {})
                    caught_up = published and all(
                        consumed.get(k, consumed.get(int(k), 0)) >= v for k, v in published.items()
                    )
                    pending = (
                        conn.execute(
                            "SELECT EXISTS(SELECT 1 FROM analytics.outbox "
                            "WHERE published_at IS NULL) "
                            "pending"
                        ).fetchone()
                        or {}
                    )["pending"]
                    at = state(conn, "evaluation_clock")
                    if caught_up and not pending and at:
                        refresh(conn, timestamp(at), cfg)
                    state(
                        conn,
                        "feature_freshness",
                        {
                            "caught_up": bool(caught_up),
                            "outbox_pending": pending,
                            "published_offsets": published,
                            "consumed_offsets": consumed,
                        },
                    )
    finally:
        logging.getLogger(__name__).info("Spark stopped: %s", query.exception())
        spark.stop()
