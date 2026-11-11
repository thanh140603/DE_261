"""`edu` developer CLI - single entry to run any job/service locally.

edu infra create-topics infra/kafka/topics.yaml
edu warehouse bootstrap
edu warehouse run --run-date 2026-09-29 [--layer gold] [--select gold.fct_submission]
edu stream lakehouse-landing
edu stream dropout-risk
edu service notification
edu service content-sync
edu batch content-reindex
edu content seed-corpus | ensure-index | register-cdc
edu stream telemetry-live [--once]
edu telemetry simulate --sessions 50
"""

from __future__ import annotations

import typer

from edu_platform.entrypoints.batch import (
    features_online_job,
    lakehouse_maintenance_job,
    seed_bronze_job,
    warehouse_job,
)
from edu_platform.entrypoints.services.content_sync import admin as content_admin
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
batch_app.command("features-online")(features_online_job.main)


@service_app.command("content-sync")
def content_sync() -> None:
    """BR8: CDC of course_content -> cache invalidation, chunks/vectors, search refresh."""
    from edu_platform.entrypoints.services.content_sync.main import main

    main()


@batch_app.command("content-reindex")
def content_reindex(
    content_id: list[str] = typer.Option(None, help="Only these content ids (repeatable)"),
    write_chunks: bool = typer.Option(True, help="Also write silver.content_chunks (Delta)"),
) -> None:
    """BR8 backfill on Spark: re-chunk, re-embed and re-index current content versions."""
    from edu_platform.entrypoints.batch.content_chunking_embedding_job import main

    main(content_id=content_id or None, write_chunks=write_chunks)


app.add_typer(content_admin.app, name="content")


@stream_app.command("session-features")
def session_features(
    once: bool = typer.Option(False, help="availableNow: process available data, then stop"),
) -> None:
    """BR2 streaming branch: session windows -> Redis + features.session.v1."""
    from edu_platform.entrypoints.streaming.session_features_job import main

    main(once=once)


@stream_app.command("telemetry-live")
def telemetry_live(
    once: bool = typer.Option(False, help="availableNow: process available data, then stop"),
) -> None:
    """BR6 fast path + BR7/BR8 live overlays (Spark Structured Streaming -> Kafka, Redis)."""
    from edu_platform.entrypoints.streaming.telemetry_live_job import main

    main(once=once)


def _benchmark_app() -> typer.Typer:
    from edu_platform.entrypoints.batch.br678_benchmark import app as benchmark

    return benchmark


app.add_typer(_benchmark_app(), name="benchmark")

telemetry_app = typer.Typer(help="Telemetry producers for the live path")
app.add_typer(telemetry_app, name="telemetry")


@telemetry_app.command("simulate")
def telemetry_simulate(
    sessions: int = typer.Option(50, help="Viewing sessions to generate (~8-14 events each)"),
    seed_value: int | None = typer.Option(None, "--seed", help="Deterministic RNG seed"),
) -> None:
    """Publish live synthetic telemetry (current timestamps) to telemetry.events.raw.v1."""
    from edu_platform.demo.live_telemetry import generate
    from edu_platform.platform.messaging.kafka_producer import KafkaEventPublisher
    from edu_platform.platform.messaging.topics import Topic

    events = generate(sessions, seed_value=seed_value)
    publisher = KafkaEventPublisher(get_settings().kafka.bootstrap_servers, client_id="edu-sim")
    for e in events:
        publisher.publish_raw(Topic.TELEMETRY_RAW.value, key=e["learner_id"], payload=e)
    publisher.flush()
    typer.echo(f"published {len(events)} telemetry events from {sessions} sessions")


# TODO: register the remaining modules under entrypoints/batch, streaming, services.


if __name__ == "__main__":
    app()
