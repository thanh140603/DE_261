"""Spark Structured Streaming: signed CDC events -> real event-time hopping windows."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from .config import AnalyticsSettings, settings
from .contracts import identity, timestamp
from .db import Db, connect, state
from .risk import refresh


def activity_windows(events: Any, cfg: AnalyticsSettings) -> Any:
    from pyspark.sql import functions as sf

    # Re-published outbox messages have the same id and event time. Retractions have distinct ids.
    return (
        events.withWatermark("event_time", f"{cfg.lateness_days} days")
        .dropDuplicatesWithinWatermark(["event_id"])
        .groupBy(
            "student_id",
            "course_id",
            sf.window("event_time", "7 days", f"{cfg.slide_seconds} seconds"),
        )
        .agg(sf.sum("delta").alias("activity_count"))
    )


def utc_window_rows(batch: Any) -> Any:
    """Collect epochs so the Python driver's local timezone cannot shift a boundary."""
    from pyspark.sql import functions as sf

    return batch.select(
        "student_id", "course_id",
        sf.unix_seconds("window.start").alias("start_seconds"),
        sf.unix_seconds("window.end").alias("end_seconds"),
        "activity_count",
    )


def score_committed_batch(conn: Db, progress: dict[str, Any], cfg: AnalyticsSettings) -> None:
    state(conn, "spark_progress", progress)
    mark = progress.get("eventTime", {}).get("watermark")
    if mark and timestamp(mark).year > 1970:
        state(conn, "stream_watermark", mark)
    published = state(conn, "published_offsets") or {}
    end_offsets = (progress.get("sources") or [{}])[0].get("endOffset") or {}
    if isinstance(end_offsets, str):
        end_offsets = json.loads(end_offsets) or {}
    consumed = {str(k): v for k, v in end_offsets.get(cfg.activity_topic, {}).items()}
    sink = state(conn, "stream") or {}
    caught_up = (
        bool(published)
        and sink.get("checkpoint") == cfg.checkpoint
        and sink.get("batch_id", -1) >= progress.get("batchId", 0)
        and all(consumed.get(k, 0) >= v for k, v in published.items())
    )
    pending = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM analytics.outbox WHERE published_at IS NULL) AS pending"
    ).fetchone()
    assert pending is not None
    at = state(conn, "evaluation_clock")
    if caught_up and not pending["pending"] and at and not cfg.benchmark_window_run:
        refresh(conn, timestamp(at), cfg, only_dirty=True)
    state(
        conn,
        "feature_freshness",
        {
            "caught_up": caught_up,
            "outbox_pending": pending["pending"],
            "published_offsets": published,
            "consumed_offsets": consumed,
        },
    )


def run() -> None:
    from pyspark.sql import functions as sf
    from pyspark.sql.types import IntegerType, StringType, StructField, StructType

    cfg = settings()
    from edu_platform.platform.batch.spark_session import build_spark
    from edu_platform.platform.config import get_settings

    spark = build_spark(
        "BR45-analytics",
        get_settings(),
        {
            "spark.sql.shuffle.partitions": "2",
            "spark.databricks.delta.snapshotPartitions": "2",
            "spark.sql.streaming.stateStore.providerClass": (
                "org.apache.spark.sql.execution.streaming.state.RocksDBStateStoreProvider"
            ),
        },
    )
    spark.sparkContext.setLogLevel("WARN")
    # Stateful schema, topic and event-time configuration form the checkpoint identity.
    if not cfg.benchmark_window_run:
        fingerprint = identity("br5-v2", cfg.activity_topic, cfg.slide_seconds, cfg.lateness_days)
        cfg = cfg.model_copy(update={"checkpoint": cfg.checkpoint + "-" + fingerprint[:12]})
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
    windows = activity_windows(events, cfg)

    def write_batch(batch: Any, batch_id: int) -> None:
        # One transaction: absolute window upserts and diagnostics.
        # foreachBatch can replay; totals replace prior values and alert keys are stable.
        with connect() as conn:
            if cfg.benchmark_window_run:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO br45_benchmark.activity_windows "
                        "(run_id,engine,student_id,course_id,window_start,window_end,"
                        "activity_count) "
                        "VALUES (%s,'spark',%s,%s,%s,%s,%s) "
                        "ON CONFLICT (run_id,engine,student_id,course_id,window_end) "
                        "DO UPDATE SET activity_count=excluded.activity_count,computed_at=now()",
                        (
                            (
                                cfg.benchmark_window_run, r.student_id, r.course_id,
                                datetime.fromtimestamp(r.start_seconds, UTC),
                                datetime.fromtimestamp(r.end_seconds, UTC),
                                r.activity_count,
                            )
                            for r in utc_window_rows(batch).toLocalIterator()
                        ),
                    )
                return
            count = 0
            rows = []
            sql = (
                "INSERT INTO analytics.activity_windows(student_id,course_id,window_start,"
                "window_end,activity_count) VALUES(%s,%s,%s,%s,%s) ON CONFLICT"
                "(student_id,course_id,window_end) DO UPDATE SET "
                "activity_count=excluded.activity_count,computed_at=now()"
            )
            for r in utc_window_rows(batch).toLocalIterator():
                rows.append(
                    (
                        r.student_id,
                        r.course_id,
                        datetime.fromtimestamp(r.start_seconds, UTC),
                        datetime.fromtimestamp(r.end_seconds, UTC),
                        r.activity_count,
                    )
                )
                count += 1
                if len(rows) >= 500:
                    with conn.cursor() as cursor:
                        cursor.executemany(sql, rows)
                    rows.clear()
            if rows:
                with conn.cursor() as cursor:
                    cursor.executemany(sql, rows)
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
    from . import lakehouse

    landing = (
        lakehouse.start(spark, cfg)
        if cfg.assessment_engine == "spark" and not cfg.engine_benchmark
        else None
    )
    try:
        while query.isActive:
            query.awaitTermination(5)
            progress = query.lastProgress
            if progress:
                with connect() as conn:
                    conn.execute("SELECT pg_advisory_xact_lock(hashtext('br45-cdc-progress'))")
                    score_committed_batch(conn, progress, cfg)
            if landing:
                if not landing.isActive:
                    raise RuntimeError(f"Delta landing stopped: {landing.exception()}")
                lakehouse.process(spark, cfg)
    finally:
        logging.getLogger(__name__).info("Spark stopped: %s", query.exception())
        spark.stop()


if __name__ == "__main__":
    run()
