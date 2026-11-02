"""Spark Structured Streaming: BR8 live engagement overlay (ADR 0014).

  telemetry.learning_events.v1 (watermarked, deduped; see video_heatmap_job) ->
  engagement points per (UTC day, course_id, learner pseudonym) with the domain's
  EngagementWeights -> Redis edu:live:engagement:<course>:<day> (absolute values).

Same verb weights as gold.fct_learner_daily_activity (both come from
analytics.domain.engagement_policy.verb_weights), so today's live score equals the score
the warehouse computes for that day once it is built. The weekly trend and the declining
flag stay in mart.engagement_trend; the overlay shows "today so far".
"""

from __future__ import annotations

from typing import Any

from edu_platform.contexts.analytics.domain.engagement_policy import verb_weights
from edu_platform.contexts.analytics.domain.model import EngagementWeights
from edu_platform.contexts.analytics.infrastructure.redis_live_overlay import RedisLiveOverlay
from edu_platform.entrypoints.streaming.video_heatmap_job import learning_events
from edu_platform.platform.messaging.topics import Topic


def score_expression(weights: EngagementWeights | None = None) -> str:
    cases = " ".join(
        f"WHEN '{verb}' THEN {weight}"
        for verb, weight in sorted(verb_weights(weights or EngagementWeights()).items())
    )
    return f"CASE verb {cases} ELSE 0.0 END"


def engagement_scores(events: Any, weights: EngagementWeights | None = None) -> Any:
    from pyspark.sql import functions as sf

    return (
        events.where("course_id IS NOT NULL AND learner_pseudonym IS NOT NULL")
        .selectExpr(
            "window(occurred_at, '1 day') AS day_window",
            "course_id",
            "learner_pseudonym",
            f"{score_expression(weights)} AS points",
        )
        .groupBy("day_window", "course_id", "learner_pseudonym")
        .agg(sf.sum("points").alias("score"))
    )


def write_engagement(overlay: RedisLiveOverlay) -> Any:
    def apply(batch: Any, batch_id: int) -> None:
        overlay.write_engagement(
            (r.day_window.start.date(), r.course_id, r.learner_pseudonym, float(r.score))
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
        engagement_scores(learning_events(spark, bootstrap, topic))
        .writeStream.outputMode("update")
        .foreachBatch(write_engagement(overlay))
        .option("checkpointLocation", checkpoint)
        .queryName("br8-live-engagement")
    )
    trigger = {"availableNow": True} if once else {"processingTime": "1 second"}
    return writer.trigger(**trigger).start()
