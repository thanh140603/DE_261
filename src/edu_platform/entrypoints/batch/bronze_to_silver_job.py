"""Spark job: bronze_to_silver_job (BR6 medallion, batch/backfill path).

Content (TODO):
- Read bronze.telemetry_raw for run_date; run NormalizeEvents (same use case as the
  Flink job - one implementation, two engines) -> MERGE into silver.learning_events.
- Also lands CDC topics into silver.enrollments / lesson_progress / submissions / grades
  (apply Debezium ops in LSN order: c/u -> upsert, d -> soft delete).
Wiring: platform.batch.spark_session.build_spark -> Delta readers/writers -> context use case.
Idempotent per (run_date) partition so Airflow retries/backfills are safe.
"""

from __future__ import annotations

import typer


def main(run_date: str = typer.Option(..., help="Partition to process, YYYY-MM-DD")) -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    typer.run(main)
