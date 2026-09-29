"""`edu` developer CLI - single entry to run any job/service locally.

edu infra create-topics infra/kafka/topics.yaml
edu batch bronze-to-silver --run-date 2026-09-29
edu stream dropout-risk
edu service notification
"""

from __future__ import annotations

import typer

from edu_platform.platform.logging import configure_logging

app = typer.Typer(help="Education data platform CLI", no_args_is_help=True)
infra_app = typer.Typer(help="Local infrastructure helpers")
batch_app = typer.Typer(help="Spark batch jobs")
stream_app = typer.Typer(help="Flink streaming jobs")
service_app = typer.Typer(help="Long-running services")
app.add_typer(infra_app, name="infra")
app.add_typer(batch_app, name="batch")
app.add_typer(stream_app, name="stream")
app.add_typer(service_app, name="service")


@app.callback()
def _init(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    configure_logging("DEBUG" if verbose else "INFO", json=False)


@infra_app.command("create-topics")
def create_topics(topics_file: str) -> None:
    """Create Kafka topics from infra/kafka/topics.yaml (idempotent)."""
    raise NotImplementedError  # TODO: AdminClient.create_topics from YAML spec


# TODO: register commands for each module under entrypoints/batch, streaming, services.
# Example:
#   from edu_platform.entrypoints.batch import bronze_to_silver_job
#   batch_app.command("bronze-to-silver")(bronze_to_silver_job.main)


if __name__ == "__main__":
    app()
