"""`edu` developer CLI - single entry to run any job/service locally.

edu infra create-topics infra/kafka/topics.yaml
edu warehouse bootstrap
edu warehouse run --run-date 2026-09-29 [--layer gold] [--select gold.fct_submission]
edu stream lakehouse-landing
edu stream dropout-risk
edu service notification
"""

from __future__ import annotations

import typer

from edu_platform.entrypoints.batch import (
    lakehouse_maintenance_job,
    seed_bronze_job,
    warehouse_job,
)
from edu_platform.entrypoints.streaming import lakehouse_landing_job
from edu_platform.platform.config import get_settings
from edu_platform.platform.logging import configure_logging

app = typer.Typer(help="Education data platform CLI", no_args_is_help=True)
infra_app = typer.Typer(help="Local infrastructure helpers")
batch_app = typer.Typer(help="Spark batch jobs")
stream_app = typer.Typer(help="Streaming jobs (Flink; Spark Structured Streaming landing)")
service_app = typer.Typer(help="Long-running services")
app.add_typer(infra_app, name="infra")
app.add_typer(batch_app, name="batch")
app.add_typer(stream_app, name="stream")
app.add_typer(service_app, name="service")


@app.callback()
def _init(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    configure_logging("DEBUG" if verbose else "INFO", json=False)


@infra_app.command("create-topics")
def create_topics(
    topics_file: str,
    replication_factor: int | None = typer.Option(None, help="Override (1 local, 3 prod)"),
) -> None:
    """Create Kafka topics from infra/kafka/topics.yaml (idempotent: existing ones are kept)."""
    from edu_platform.platform.messaging.admin import create_topics_from_file

    created = create_topics_from_file(
        topics_file, get_settings().kafka.bootstrap_servers, replication_factor
    )
    typer.echo(f"created {len(created)} topic(s): {', '.join(created) or '-'}")


# Lakehouse warehouse (ADR 0011/0011): DDL bootstrap, model builds, synthetic bronze data.
warehouse_job.app.command("seed-bronze")(seed_bronze_job.seed_bronze)
app.add_typer(warehouse_job.app, name="warehouse")
stream_app.command("lakehouse-landing")(lakehouse_landing_job.main)
batch_app.command("lakehouse-maintenance")(lakehouse_maintenance_job.main)

# TODO: register the remaining modules under entrypoints/batch, streaming, services.


if __name__ == "__main__":
    app()
