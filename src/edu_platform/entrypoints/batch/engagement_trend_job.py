"""Spark job: engagement_trend_job (BR8 weekly).

Content (TODO):
- ComputeEngagementTrend(run_date) -> gold.engagement_trend.
Wiring: platform.batch.spark_session.build_spark -> Delta readers/writers -> context use case.
Idempotent per (run_date) partition so Airflow retries/backfills are safe.
"""

from __future__ import annotations

import typer


def main(run_date: str = typer.Option(..., help="Partition to process, YYYY-MM-DD")) -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    typer.run(main)
