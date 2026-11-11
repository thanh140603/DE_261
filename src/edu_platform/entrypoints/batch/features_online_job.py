"""Materialise the latest offline feature partition into the Redis online store (BR2).

The lakehouse is the offline store (``features.learner_longterm``, partitioned by
``as_of_date``); Spark writes it. This job is the bridge to the online store and
is idempotent: it overwrites each learner's JSON document, so a retry or a
backfill of the same date leaves the same values.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

import typer

from edu_platform.contexts.recommendation.domain.model import LongTermFeatures
from edu_platform.contexts.recommendation.infrastructure.redis_online_store import (
    RedisOnlineFeatureStore,
)
from edu_platform.platform.config import get_settings
from edu_platform.platform.logging import get_logger
from edu_platform.platform.storage.redis_client import create_redis_client

log = get_logger(__name__)


def _to_features(row: Any) -> LongTermFeatures:
    return LongTermFeatures(
        learner_pseudonym=str(row["learner_pseudonym"]),
        completion_rate_30d=float(row["completion_rate_30d"]),
        avg_pass_rate_30d=float(row["avg_pass_rate_30d"]),
        active_days_30d=int(row["active_days_30d"]),
        preferred_platform=str(row["preferred_platform"] or "web"),
        skill_mastery={str(k): float(v) for k, v in (row["skill_mastery"] or {}).items()},
        computed_at=row["computed_at"],
    )


def write_partition(
    rows: Iterable[Any], redis_url: str, store: RedisOnlineFeatureStore | None = None
) -> None:
    target = store or RedisOnlineFeatureStore(create_redis_client(redis_url))
    for row in rows:
        target.put_longterm(_to_features(row))


def run(
    spark: Any,
    redis_url: str,
    run_date: date | None = None,
    *,
    source: Any | None = None,
) -> tuple[date | None, int]:
    from pyspark.sql import functions as F  # noqa: N812

    table = source if source is not None else spark.table("features.learner_longterm")
    if run_date is not None:
        table = table.where(F.col("as_of_date") == run_date.isoformat())
        latest: date | None = run_date
    else:
        row = table.agg(F.max("as_of_date").alias("latest")).collect()[0]
        latest = row["latest"]
        if latest is None:
            return None, 0
        table = table.where(F.col("as_of_date") == latest)
    count = table.count()
    if count:
        table.foreachPartition(lambda rows: write_partition(rows, redis_url))
    return latest, count


def main(
    run_date: str | None = typer.Option(None, help="Partition YYYY-MM-DD; default latest"),
) -> None:
    from edu_platform.platform.batch.spark_session import build_spark

    settings = get_settings()
    day = date.fromisoformat(run_date) if run_date else None
    spark = build_spark("edu-features-online", settings)
    latest, count = run(spark, settings.redis_url, day)
    log.info("online features materialised", as_of_date=str(latest), rows=count)
    typer.echo(f"materialised {count} learner feature row(s) for {latest}")


if __name__ == "__main__":
    typer.run(main)
