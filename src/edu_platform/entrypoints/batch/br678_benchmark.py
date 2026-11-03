"""Reproducible BR6/BR7/BR8 measurements; every number is measured, none is estimated.

  edu benchmark marts    --days 35 --days 70 --days 140 --repeat 2 --out mart_build.csv
      (Spark: isolated in-memory catalog + local lakehouse dir per run; never touches the
       demo warehouse. Run inside the spark-jobs container.)
  edu benchmark serving  --requests 30 --out serving_latency.csv          (HTTP, running stack)
  edu benchmark content  --publishes 20 --out content_sync_latency.csv    (HTTP + PostgreSQL)
  edu benchmark live     --sessions 25 --sessions 100 --sessions 400 --repeat 3 \
                         --out live_overlay.csv
  edu benchmark environment --out environment.json

All synthetic: seeded bronze (seed_bronze_job), generated transcripts and live sessions.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import statistics
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(help="BR6/BR7/BR8 benchmarks (docs/evidence/br678)")
API = os.getenv("EDU_BENCH_API", "http://localhost:8000/api")
TOKENS = {"admin": "admin-demo", "instructor": "instructor-demo"}


def _append(out: Path, row: dict[str, Any]) -> None:
    """One row as soon as it is measured: a later crash keeps what was measured."""
    out.parent.mkdir(parents=True, exist_ok=True)
    new = not out.exists() or out.stat().st_size == 0
    with out.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        if new:
            writer.writeheader()
        writer.writerow(row)


def _write(out: Path, rows: list[dict[str, Any]]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    typer.echo(f"wrote {len(rows)} rows to {out}")


def _get(path: str, role: str) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{API}{path}", headers={"Authorization": f"Bearer {TOKENS[role]}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _post(path: str, role: str, body: dict[str, Any]) -> Any:
    request = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {TOKENS[role]}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


# --- marts (Spark) ------------------------------------------------------------------------
@app.command("marts")
def marts(
    days: list[int] = typer.Option([35, 70, 140], help="Days of synthetic activity (scale)"),
    repeat: int = typer.Option(2, help="Repetitions per size"),
    first_repeat: int = typer.Option(1, help="Label of the first repetition (resumed runs)"),
    end_date: str = typer.Option("2026-10-17"),
    out: Path = typer.Option(Path("mart_build.csv")),
) -> None:
    """Full warehouse build (bronze -> silver -> gold -> marts) per activity volume; one row
    appended per run. Prefer one process per run (as production runs): repeated builds in
    one driver accumulate memory and are not representative."""
    from edu_platform.entrypoints.batch.seed_bronze_job import Generator
    from edu_platform.entrypoints.batch.warehouse_job import build_runner
    from edu_platform.platform.config import get_settings

    base = get_settings()
    end = date.fromisoformat(end_date)
    rows: list[dict[str, Any]] = []
    for size in days:
        for rep in range(first_repeat, first_repeat + repeat):
            root = f"file:///tmp/br678-bench/{size}-{rep}-{uuid.uuid4().hex[:6]}"
            settings = base.model_copy(
                update={
                    "lakehouse": base.lakehouse.model_copy(update={"lakehouse_root": root}),
                    "spark": base.spark.model_copy(update={"hive_metastore_uri": None}),
                }
            )
            runner = build_runner(settings, "edu-br678-benchmark")
            spark = runner.spark
            for schema in ("bronze", "silver", "gold", "mart", "features", "ops"):
                spark.sql(f"DROP DATABASE IF EXISTS {schema} CASCADE")
            runner.bootstrap()
            gen = Generator(end, size)
            gen.reference()
            gen.activity()
            for table, data in {
                "bronze.telemetry_raw": gen.out.telemetry,
                "bronze.cdc_events": gen.out.cdc,
                "bronze.domain_events": gen.out.events,
            }.items():
                spark.createDataFrame(data, spark.table(table).schema).writeTo(table).append()
            started = time.perf_counter()
            results = runner.run(end, start_date=gen.start.date() - timedelta(days=31))
            total = time.perf_counter() - started
            by_layer: dict[str, float] = {}
            for r in results:
                layer = r.model.split(".")[0]
                by_layer[layer] = by_layer.get(layer, 0.0) + r.seconds
            seconds = {r.model: r.seconds for r in results}
            events = spark.sql("SELECT count(*) AS n FROM silver.learning_events").first()
            rows.append(
                {
                    "days": size,
                    "repeat": rep,
                    "bronze_telemetry_rows": len(gen.out.telemetry),
                    "silver_events": events.n if events else 0,
                    "models": len(results),
                    "failed_models": sum(r.status != "success" for r in results),
                    "total_s": round(total, 3),
                    "silver_s": round(by_layer.get("silver", 0.0), 3),
                    "gold_s": round(by_layer.get("gold", 0.0), 3),
                    "mart_s": round(by_layer.get("mart", 0.0), 3),
                    "org_progress_s": round(seconds.get("mart.org_progress", 0.0), 3),
                    "video_heatmap_s": round(seconds.get("mart.video_heatmap", 0.0), 3),
                    "engagement_trend_s": round(seconds.get("mart.engagement_trend", 0.0), 3),
                    "fct_video_second_activity_s": round(
                        seconds.get("gold.fct_video_second_activity", 0.0), 3
                    ),
                }
            )
            _append(out, rows[-1])
            typer.echo(f"days={size} rep={rep}: {total:.1f}s, {rows[-1]['silver_events']} events")


# --- serving (HTTP) --------------------------------------------------------------------------
@app.command("serving")
def serving(
    requests: int = typer.Option(30, help="Requests per endpoint and mode"),
    trino_host: str = typer.Option("localhost"),
    trino_port: int = typer.Option(8091),
    out: Path = typer.Option(Path("serving_latency.csv")),
) -> None:
    """Per BR: the uncached warehouse reads an API request performs (TrinoMartReader against
    Trino, same calls as the router) vs the API over HTTP with the mart cache warm."""
    from edu_platform.contexts.analytics.infrastructure.trino_mart_reader import (
        TrinoMartReader,
        trino_query,
    )
    from edu_platform.platform.config import TrinoSettings

    reader = TrinoMartReader(trino_query(TrinoSettings(host=trino_host, port=trino_port)))
    direct: dict[str, Callable[[], object]] = {
        "BR6": lambda: reader.org_progress("org-acme", None),
        "BR7": lambda: (reader.video("v-sql-joins"), reader.video_heatmap("v-sql-joins", None)),
        "BR8": lambda: reader.engagement_trend("c-py-201", None),
    }
    api = {
        "BR6": ("admin", "/admin/organisations/org-acme/skill-progress?live=false"),
        "BR7": ("instructor", "/instructor/videos/v-sql-joins/interaction-heatmap?live=false"),
        "BR8": ("instructor", "/instructor/courses/c-py-201/engagement-trend?live=false"),
    }
    rows: list[dict[str, Any]] = []
    for br in ("BR6", "BR7", "BR8"):
        _get(api[br][1], api[br][0])  # warm the API cache
        for i in range(requests):
            started = time.perf_counter()
            direct[br]()
            rows.append({"br": br, "mode": "trino_uncached", "request": i + 1, "status": 200,
                         "ms": round((time.perf_counter() - started) * 1000, 2)})  # fmt: skip
        for i in range(requests):
            started = time.perf_counter()
            status, _ = _get(api[br][1], api[br][0])
            rows.append({"br": br, "mode": "api_cached", "request": i + 1, "status": status,
                         "ms": round((time.perf_counter() - started) * 1000, 2)})  # fmt: skip
    _write(out, rows)
    for br in ("BR6", "BR7", "BR8"):
        for mode in ("trino_uncached", "api_cached"):
            ms = [r["ms"] for r in rows if r["br"] == br and r["mode"] == mode]
            typer.echo(f"{br} {mode}: median {statistics.median(ms):.1f} ms, max {max(ms):.1f} ms")


# --- content sync (HTTP + PostgreSQL) ------------------------------------------------------
@app.command("content")
def content(
    publishes: int = typer.Option(20),
    dsn: str = typer.Option("postgresql://lms:lms@localhost:5433/lms"),
    out: Path = typer.Option(Path("content_sync_latency.csv")),
) -> None:
    """Instructor publish -> CDC -> sync -> searchable, on a throwaway content row."""
    import psycopg

    cid = f"v-bench-{uuid.uuid4().hex[:6]}"
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO public.course_content (content_id, course_id, content_type, title, "
            "version, object_key, duration_sec) VALUES (%s, 'c-sql-101', 'video_transcript', "
            "'Benchmark probe', 1, 'courses/c-sql-101/v-sql-select/v1.vtt', 60)",
            (cid,),
        )
    rows: list[dict[str, Any]] = []
    try:
        _wait(lambda: _get(f"/instructor/content/{cid}/sync-status", "instructor")[1]["in_sync"])
        for i in range(publishes):
            marker = f"probe{uuid.uuid4().hex[:10]}"
            started = time.perf_counter()
            version = _post(
                f"/instructor/content/{cid}/versions",
                "instructor",
                {"body": f"# Probe\n\nBenchmark {marker} keeps rows joins."},
            )["version"]
            accepted = time.perf_counter()
            _wait(
                lambda m=marker, v=version: any(
                    h["content_id"] == cid and h["version"] == v
                    for h in _get(
                        f"/instructor/courses/c-sql-101/search?q={m}&mode=keyword", "instructor"
                    )[1]["hits"]
                ),
                interval=0.05,
            )
            done = time.perf_counter()
            rows.append(
                {
                    "publish": i + 1,
                    "version": version,
                    "api_accept_ms": round((accepted - started) * 1000, 2),
                    "publish_to_searchable_ms": round((done - started) * 1000, 2),
                }
            )
    finally:
        with psycopg.connect(dsn) as conn:  # CDC delete also exercises removal
            conn.execute("DELETE FROM public.course_content WHERE content_id = %s", (cid,))
    _write(out, rows)
    ms = sorted(r["publish_to_searchable_ms"] for r in rows)
    typer.echo(f"publish -> searchable: median {statistics.median(ms):.0f} ms, max {ms[-1]:.0f} ms")


# --- live overlays (Kafka + HTTP) ----------------------------------------------------------------
@app.command("live")
def live(
    sessions: list[int] = typer.Option([25, 100, 400], help="Sessions per burst (load)"),
    repeat: int = typer.Option(3),
    bootstrap: str = typer.Option("localhost:9092"),
    out: Path = typer.Option(Path("live_overlay.csv")),
) -> None:
    """Burst of live sessions -> Kafka -> telemetry-live -> Redis -> API: time until the
    busiest video's overlay contains every on-time interaction of the burst."""
    from confluent_kafka import Producer

    from edu_platform.demo.live_telemetry import generate

    producer = Producer({"bootstrap.servers": bootstrap})
    rows: list[dict[str, Any]] = []
    for size in sessions:
        for rep in range(1, repeat + 1):
            events = generate(size, seed_value=int(time.time() * 1000))  # unique event ids
            horizon = datetime.now(tz=UTC) - timedelta(minutes=5)
            want: Counter[str] = Counter()
            for e in events:
                at = e.get("occurred_at")
                late = at is not None and datetime.fromisoformat(at) < horizon
                if e["verb"] in ("played", "paused", "seeked") and e.get("content_id") and not late:
                    want[e["content_id"]] += 1
            target, expected = want.most_common(1)[0]
            before = _live_total(target)
            started = time.perf_counter()
            for e in events:
                producer.produce(
                    "telemetry.events.raw.v1", key=e["learner_id"], value=json.dumps(e).encode()
                )
            producer.flush(30)
            published = time.perf_counter()
            _wait(lambda t=target, n=before + expected: _live_total(t) >= n, timeout=180)
            done = time.perf_counter()
            rows.append({"sessions": size, "repeat": rep, "raw_events": len(events),
                         "target_content": target, "target_interactions": expected,
                         "publish_ms": round((published - started) * 1000, 2),
                         "event_to_api_ms": round((done - started) * 1000, 2),
                         "events_per_s": round(len(events) / (done - started), 1),
                         "exact": _live_total(target) == before + expected})  # fmt: skip
            typer.echo(f"sessions={size} rep={rep}: {rows[-1]['event_to_api_ms']:.0f} ms")
    _write(out, rows)


def _live_total(content_id: str) -> int:
    _, body = _get(f"/instructor/videos/{content_id}/interaction-heatmap", "instructor")
    seconds = ((body or {}).get("live") or {}).get("seconds", [])
    return sum(s["play"] + s["pause"] + s["seek"] for s in seconds)


def _wait(check: Any, *, timeout: float = 120, interval: float = 0.2) -> None:
    deadline = time.perf_counter() + timeout
    while not check():
        if time.perf_counter() > deadline:
            raise TimeoutError("condition not reached")
        time.sleep(interval)


# --- environment -------------------------------------------------------------------------------
@app.command("environment")
def environment(out: Path = typer.Option(Path("environment.json"))) -> None:
    import subprocess

    def docker(fmt: str) -> str:
        try:
            return subprocess.run(
                ["docker", "info", "--format", fmt], capture_output=True, text=True, timeout=20
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "unavailable"

    info = {
        "measured_at": datetime.now(tz=UTC).isoformat(),
        "host_platform": platform.platform(),
        "host_python": platform.python_version(),
        "host_logical_cpus": os.cpu_count(),
        "docker_server": docker("{{.ServerVersion}}"),
        "docker_vm_cpus": docker("{{.NCPU}}"),
        "docker_vm_memory_bytes": docker("{{.MemTotal}}"),
        "spark_image": "Spark 3.5.5, Delta 3.3.2, Python 3.11, Java 17 (infra/spark/Dockerfile)",
        "telemetry_live": "local[2], shuffle partitions 2, 1 s triggers, checkpoints s3a (MinIO)",
        "trino": "478, single node, heap 1.2 GB (infra/trino/jvm.config)",
        "opensearch": "2.17.1, single node, heap 512 MB",
        "dataset": "SYNTHETIC: seed_bronze_job, demo/corpus.py, demo/live_telemetry.py",
    }
    out.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"wrote {out}")
