"""Spark job: batch_features_job (BR2 batch branch).

Content (TODO):
- ComputeBatchFeatures for each FeatureGroup in the registry as of run_date.
- Write offline store (gold.features_<group>) then MaterializeOnlineFeatures to Redis.
Wiring: platform.batch.spark_session.build_spark -> Delta readers/writers -> context use case.
Idempotent per (run_date) partition so Airflow retries/backfills are safe.
"""

from __future__ import annotations

import typer


def main(run_date: str = typer.Option(..., help="Partition to process, YYYY-MM-DD")) -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    typer.run(main)
