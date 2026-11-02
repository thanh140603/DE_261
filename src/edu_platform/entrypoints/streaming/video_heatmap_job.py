"""Spark Structured Streaming: BR7 live heatmap overlay (ADR 0014).

  telemetry.learning_events.v1 (event time, watermark 5 min = LatenessPolicy, deduped on
  event_id) -> play / pause / seek counts and approximate distinct learners per
  (UTC day, content_id, second) -> Redis edu:live:heatmap:<content>:<day> (absolute values).

The authoritative per-version heatmap stays the warehouse mart.video_heatmap; this overlay
only covers days the mart has not built yet. Events later than the watermark are left to
the mart. Positions are not clamped here (the stream does not know video durations).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from edu_platform.contexts.analytics.infrastructure.redis_live_overlay import RedisLiveOverlay
from edu_platform.contexts.telemetry.domain.events import LatenessPolicy
from edu_platform.platform.messaging.topics import Topic

LEARNING_EVENT_SCHEMA = (
    "event_id STRING, learner_pseudonym STRING, course_id STRING, content_id STRING, "
    "session_id STRING, verb STRING, platform STRING, occurred_at TIMESTAMP, "
    "received_at TIMESTAMP, event_date DATE, video_position_sec INT, is_late BOOLEAN, "
    "lateness_sec DOUBLE, schema_version STRING"
)


def watermark() -> str:
    seconds = int(LatenessPolicy().max_lateness / timedelta(seconds=1))
    return f"{seconds} seconds"


def learning_events(spark: Any, bootstrap: str, topic: str = Topic.LEARNING_EVENTS.value) -> Any:
    """Normalised events, event-time watermarked and deduplicated on event_id."""
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("failOnDataLoss", "false")
        .load()
        .selectExpr(f"from_json(CAST(value AS STRING), '{LEARNING_EVENT_SCHEMA}') AS e")
        .select("e.*")
        .where("event_id IS NOT NULL AND occurred_at IS NOT NULL")
        .withWatermark("occurred_at", watermark())
        .dropDuplicatesWithinWatermark(["event_id"])
    )


def heatmap_counts(events: Any) -> Any:
    return (
        events.where(
            "content_id IS NOT NULL AND video_position_sec IS NOT NULL "
            "AND verb IN ('played', 'paused', 'seeked')"
        )
        .selectExpr(
            "window(occurred_at, '1 day') AS day_window",
            "content_id",
            "video_position_sec",
            "verb",
            "learner_pseudonym",
        )
        .groupBy("day_window", "content_id", "video_position_sec")
        .agg(
            _expr("count_if(verb = 'played') AS play"),
            _expr("count_if(verb = 'paused') AS pause"),
            _expr("count_if(verb = 'seeked') AS seek"),
            _expr("approx_count_distinct(learner_pseudonym) AS learners"),
        )
    )


def _expr(sql: str) -> Any:
    from pyspark.sql import functions as sf

    return sf.expr(sql)


def write_heatmap(overlay: RedisLiveOverlay) -> Any:
    def apply(batch: Any, batch_id: int) -> None:
        overlay.write_heatmap(
            (
                r.day_window.start.date(),
                r.content_id,
                int(r.video_position_sec),
                int(r.play),
                int(r.pause),
                int(r.seek),
                int(r.learners),
            )
            for r in batch.toLocalIterator()
        )

    return apply


def start(
    spark: Any,
    bootstrap: str,
    overlay: RedisLiveOverlay,
    checkpoint: str,
    *,
    once: bool = False,
    topic: str = Topic.LEARNING_EVENTS.value,
) -> Any:
    writer = (
        heatmap_counts(learning_events(spark, bootstrap, topic))
        .writeStream.outputMode("update")
        .foreachBatch(write_heatmap(overlay))
        .option("checkpointLocation", checkpoint)
        .queryName("br7-live-heatmap")
    )
    trigger = {"availableNow": True} if once else {"processingTime": "1 second"}
    return writer.trigger(**trigger).start()
