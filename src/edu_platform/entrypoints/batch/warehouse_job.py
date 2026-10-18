"""Spark job: lakehouse warehouse (bronze -> silver -> gold -> marts / features).

Composition root of the warehouse runner:
- builds the Spark session (Delta + S3A + Hive Metastore, ADR 0010),
- registers the ``pseudonymize`` SQL function (same HMAC key as the telemetry context, so
  pseudonyms from CDC, domain events and telemetry join),
- injects the business thresholds from the analytics / risk domain value objects as SQL
  parameters, so marts and use cases cannot drift apart,
- registers python models (silver.learning_events = NormalizeEvents in Spark).

  edu warehouse bootstrap
  edu warehouse run --run-date 2026-10-18 [--layer gold] [--select gold.fct_submission]
  edu warehouse run --run-date 2026-10-18 --start-date 2026-09-01     # backfill a range
Idempotent per (run_date, window): Airflow retries and backfills are safe.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import typer

from edu_platform.contexts.analytics.domain.engagement_policy import DEFAULT_DECLINE_RATIO
from edu_platform.contexts.analytics.domain.model import (
    AnomalyThreshold,
    EngagementWeights,
    MinCohortPolicy,
)
from edu_platform.contexts.risk.domain.model import SlidingWindowPolicy
from edu_platform.contexts.telemetry.infrastructure.hmac_pseudonymizer import HmacPseudonymizer
from edu_platform.contexts.telemetry.infrastructure.spark_normalizer import normalize_to_silver
from edu_platform.platform.batch.spark_session import build_spark
from edu_platform.platform.config import Settings, get_settings
from edu_platform.platform.warehouse.registry import load_registry
from edu_platform.platform.warehouse.runner import SOURCE_VIEW, RunContext, WarehouseRunner

PII_KEY_VERSION = 1
FEATURE_GROUP_VERSION = 1  # schemas/features/v1/feature_groups.yaml learner_longterm

app = typer.Typer(help="Lakehouse warehouse: DDL bootstrap and model builds")


def policy_params() -> dict[str, object]:
    """Business thresholds owned by the domain, exposed to SQL as ${name} parameters."""
    anomaly = AnomalyThreshold()
    weights = EngagementWeights()
    return {
        "anomaly_min_attempts": anomaly.min_attempts,
        "anomaly_max_pass_rate": anomaly.max_pass_rate,
        "anomaly_min_delta": anomaly.min_delta_from_median,
        "min_cohort_k": MinCohortPolicy().k,
        "w_login": weights.login,
        "w_view": weights.view,
        "w_attempt": weights.attempt,
        "w_discussion": weights.discussion,
        "decline_ratio": DEFAULT_DECLINE_RATIO,
        "risk_alert_threshold": SlidingWindowPolicy().alert_threshold,
        "assessment_window_days": 28,
        "heatmap_window_days": 28,
        "engagement_weeks": 4,
        "feature_window_days": 30,
        "feature_version": FEATURE_GROUP_VERSION,
    }


def build_runner(settings: Settings, app_name: str = "edu-warehouse") -> WarehouseRunner:
    spark = build_spark(app_name, settings)
    secret = settings.pii_hmac_secret.get_secret_value().encode("utf-8")
    pseudonymizer = HmacPseudonymizer(secret, PII_KEY_VERSION)
    spark.udf.register(
        "pseudonymize",
        lambda raw: None if raw is None else pseudonymizer.pseudonymize(str(raw)),
        "string",
    )

    def learning_events(session: Any, ctx: RunContext) -> None:
        normalize_to_silver(session, SOURCE_VIEW, secret, PII_KEY_VERSION)

    warehouse_dir = Path(settings.spark.warehouse_dir)
    return WarehouseRunner(
        spark,
        load_registry(warehouse_dir / "models.yaml"),
        warehouse_dir,
        params={"lakehouse_root": settings.lakehouse.lakehouse_root, **policy_params()},
        python_models={"silver.learning_events": learning_events},
    )


@app.command("bootstrap")
def bootstrap() -> None:
    """Create schemas and tables in the Hive Metastore (idempotent)."""
    runner = build_runner(get_settings(), "edu-warehouse-bootstrap")
    applied = runner.bootstrap()
    typer.echo(f"applied {len(applied)} DDL files: {', '.join(applied)}")


@app.command("run")
def run(
    run_date: str = typer.Option(..., help="Logical date (YYYY-MM-DD), Airflow {{ ds }}"),
    layer: list[str] = typer.Option(None, help="silver | gold | mart | features (repeatable)"),
    select: list[str] = typer.Option(None, help="Exact model name, e.g. gold.fct_submission"),
    start_date: str | None = typer.Option(None, help="Backfill: window start instead of lookback"),
    skip_quality: bool = typer.Option(False, help="Do not evaluate quality gates"),
) -> None:
    """Build models for run_date (all layers unless --layer / --select)."""
    runner = build_runner(get_settings())
    results = runner.run(
        date.fromisoformat(run_date),
        layers=layer or None,
        select=select or None,
        start_date=date.fromisoformat(start_date) if start_date else None,
        skip_quality=skip_quality,
    )
    for r in results:
        typer.echo(f"{r.status:8} {r.model:40} rows={r.rows_written} version={r.table_version}")


if __name__ == "__main__":
    app()
