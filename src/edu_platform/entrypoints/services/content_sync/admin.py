"""Operational commands for the BR8 content pipeline (idempotent; safe to rerun).

  edu content seed-corpus      upload a transcript for every LMS content row lacking one
  edu content ensure-index     create the OpenSearch chunk + meta indices
  edu content register-cdc     create/update the Debezium LMS connector (course_content incl.)

Order on a fresh stack: seed-corpus -> ensure-index -> register-cdc, so the connector's
initial snapshot never points the sync at a missing object.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import typer

from edu_platform.contexts.content.infrastructure.postgres_content_catalog import (
    PostgresContentCatalog,
)
from edu_platform.demo.corpus import TRANSCRIPTS
from edu_platform.entrypoints.services.content_sync.main import build_adapters
from edu_platform.platform.config import get_settings
from edu_platform.platform.storage.object_storage import create_s3_client

ROOT = Path(__file__).resolve().parents[5]
app = typer.Typer(help="BR8 content pipeline: corpus, search index, CDC connector")


@app.command("seed-corpus")
def seed_corpus() -> None:
    """Upload a transcript for each course_content row whose object does not exist yet."""
    settings = get_settings()
    s3 = create_s3_client(settings.lakehouse)
    catalog = PostgresContentCatalog(settings.postgres_dsn.get_secret_value())
    created = 0
    for entry in catalog.all_entries():
        try:
            s3.head_object(Bucket=settings.corpus_bucket, Key=entry.object_key)
            continue
        except s3.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                raise
        body = (
            TRANSCRIPTS.get(entry.content_id) or f"# {entry.title}\n\nTranscript of {entry.title}."
        )
        s3.put_object(Bucket=settings.corpus_bucket, Key=entry.object_key, Body=body.encode())
        created += 1
    typer.echo(f"corpus: {created} object(s) uploaded to s3://{settings.corpus_bucket}")


@app.command("ensure-index")
def ensure_index() -> None:
    build_adapters(get_settings()).index.ensure_indices()
    typer.echo("opensearch: edu-content-chunks, edu-content-meta ready")


@app.command("register-cdc")
def register_cdc(
    connect_url: str = typer.Option("http://localhost:8083", help="Kafka Connect REST URL"),
    config_file: Path = typer.Option(ROOT / "infra" / "debezium" / "postgres-connector.json"),
) -> None:
    """PUT the connector config (creates or updates; no error when it already exists)."""
    spec = json.loads(config_file.read_text("utf-8"))
    request = urllib.request.Request(
        f"{connect_url}/connectors/{spec['name']}/config",
        data=json.dumps(spec["config"]).encode(),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        typer.echo(f"connector {spec['name']}: HTTP {response.status}")
