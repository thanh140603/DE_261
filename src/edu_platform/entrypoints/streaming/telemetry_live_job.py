"""Spark Structured Streaming app: telemetry fast path + BR7/BR8 live overlays (ADR 0014).

Three checkpointed queries in one driver:
  telemetry-normalize   raw -> telemetry.learning_events.v1 / DLQ (telemetry_normalization_job)
  br7-live-heatmap      learning events -> Redis heatmap overlay   (video_heatmap_job)
  br8-live-engagement   learning events -> Redis engagement overlay (engagement_trend_job)

  edu stream telemetry-live            # continuous (2 s / 5 s triggers)
  edu stream telemetry-live --once     # drain what is available, then stop (availableNow)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from edu_platform.contexts.analytics.infrastructure.redis_live_overlay import RedisLiveOverlay
from edu_platform.entrypoints.streaming import (
    engagement_trend_job,
    telemetry_normalization_job,
    video_heatmap_job,
)
from edu_platform.platform.config import Settings, get_settings
from edu_platform.platform.logging import get_logger
from edu_platform.platform.messaging.topics import Topic
from edu_platform.platform.storage.redis_client import create_redis_client

log = get_logger(__name__)


def run(spark: Any, settings: Settings, overlay: RedisLiveOverlay, *, once: bool) -> None:
    bootstrap = settings.kafka.bootstrap_servers
    root = settings.stream_checkpoint_root.rstrip("/") + "/telemetry-live"
    secret = settings.pii_hmac_secret.get_secret_value().encode("utf-8")
    normalize = telemetry_normalization_job.start(
        spark, secret, bootstrap, f"{root}/normalize", once=once
    )
    if once:  # aggregate only after everything available was normalised
        normalize.awaitTermination()
    heatmap = video_heatmap_job.start(spark, bootstrap, overlay, f"{root}/heatmap", once=once)
    engagement = engagement_trend_job.start(
        spark, bootstrap, overlay, f"{root}/engagement", once=once
    )
    log.info("telemetry live queries started", checkpoints=root, once=once)
    if once:
        heatmap.awaitTermination()
        engagement.awaitTermination()
    else:
        _log_progress(spark, every_seconds=settings.stream_progress_seconds)
        spark.streams.awaitAnyTermination()


def _log_progress(spark: Any, every_seconds: int) -> None:
    """Background thread: per query, the last micro-batch's size and where its time went."""
    import threading

    def loop() -> None:
        while spark.streams.active:
            for q in spark.streams.active:
                p = q.lastProgress
                if p and p["numInputRows"]:  # idle batches carry no information
                    log.info(
                        "stream progress",
                        query=q.name,
                        batch=p["batchId"],
                        rows=p["numInputRows"],
                        duration_ms=p["durationMs"],
                        state_rows=sum(
                            o.get("numRowsTotal", 0) for o in p.get("stateOperators", [])
                        ),
                    )
            threading.Event().wait(every_seconds)

    threading.Thread(target=loop, name="stream-progress", daemon=True).start()


TOPICS = {Topic.TELEMETRY_RAW.value, Topic.LEARNING_EVENTS.value, Topic.TELEMETRY_DLQ.value}
CATALOGUE = Path(__file__).resolve().parents[4] / "infra" / "kafka" / "topics.yaml"


def main(
    once: bool = typer.Option(False, help="availableNow: process available data, then stop"),
) -> None:
    from edu_platform.platform.batch.spark_session import build_spark
    from edu_platform.platform.messaging.admin import create_topics_from_file

    settings = get_settings()
    # Spark's Kafka source does not create topics; a missing one fails the query at start
    created = create_topics_from_file(str(CATALOGUE), settings.kafka.bootstrap_servers, only=TOPICS)
    log.info("telemetry topics ready", created=created)
    spark = build_spark("edu-telemetry-live", settings)
    overlay = RedisLiveOverlay(create_redis_client(settings.redis_url))
    run(spark, settings, overlay, once=once)
