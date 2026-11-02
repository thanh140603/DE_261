"""Spark job: content_chunking_embedding_job (BR8 corpus backfill / reindex).

Re-chunks, re-embeds and re-indexes the *current* version of every content item (or the
selected ones) at corpus scale, e.g. after a chunking-strategy or embedding-model change,
after restoring OpenSearch, or on a fresh stack. Distribution: one Spark task per slice
of items; each task builds its own clients and runs the same SyncContentChange use case as
the content-sync service (forced), so there is a single chunking/indexing implementation.
Chunks are also written to ``silver.content_chunks`` (lineage; Spark owns Delta, ADR 0011).

Source: ``silver.content_versions`` (CDC history of course_content) - latest non-deleted
version per content_id. Idempotent: chunk ids are deterministic, a rerun replaces the
rows of the versions it processed and re-indexes the same documents. Failures are isolated
per item (e.g. a missing object): the other items are still reindexed and written, then the
job exits non-zero listing the failures so the scheduler sees them.

  edu batch content-reindex [--content-id v-sql-joins] [--no-write-chunks]
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from edu_platform.contexts.content.application.sync_content_change import SyncContentChange
from edu_platform.contexts.content.domain.model import ContentType
from edu_platform.contexts.content.domain.sync_policy import ContentChange
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId

CHUNK_COLUMNS = (
    "chunk_id STRING, content_id STRING, version INT, ordinal INT, section_path ARRAY<STRING>, "
    "text STRING, token_count INT, start_offset INT, end_offset INT, embedding_ref STRING, "
    "embedding_model STRING, chunked_at TIMESTAMP, _processed_at TIMESTAMP"
)
CURRENT_VERSIONS = """
SELECT content_id, course_id, content_type, title, version, object_key, published_at
FROM (
  SELECT *, row_number() OVER (PARTITION BY content_id ORDER BY version DESC) AS rn
  FROM silver.content_versions
) WHERE rn = 1 AND NOT is_deleted
"""


@dataclass
class Worker:
    """What one Spark task needs: the use case, a flush for its events, the model name."""

    sync: SyncContentChange
    flush: Callable[[], None]
    embedding_model: str


WorkerFactory = Callable[[], Worker]


def default_worker() -> Worker:
    """Production wiring, built inside each task (clients are not picklable)."""
    from edu_platform.entrypoints.services.content_sync.main import build_adapters, build_sync
    from edu_platform.platform.config import get_settings
    from edu_platform.platform.messaging.kafka_producer import KafkaEventPublisher

    settings = get_settings()
    adapters = build_adapters(settings)
    publisher = KafkaEventPublisher(settings.kafka.bootstrap_servers, client_id="edu-reindex")
    return Worker(build_sync(adapters, publisher), publisher.flush, adapters.index.embedding_model)


def sync_partition(rows: Iterable[Any], factory: WorkerFactory) -> Iterator[tuple[Any, ...]]:
    worker = factory()
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    for row in rows:
        published_at = row["published_at"]
        change = ContentChange(
            content_id=ContentId(row["content_id"]),
            course_id=CourseId(row["course_id"]),
            content_type=ContentType(row["content_type"]),
            title=row["title"],
            version=int(row["version"]),
            object_key=row["object_key"],
            changed_at=published_at.replace(tzinfo=UTC) if published_at else datetime.now(tz=UTC),
        )
        try:
            result = worker.sync.execute(change, force=True)
        except Exception as exc:  # isolate: one bad item must not abort the backfill
            # failure marker row: no chunk_id; the error travels in ``text``
            yield (
                None, change.content_id, change.version, -1, [], f"{type(exc).__name__}: {exc}",
                0, 0, 0, None, worker.embedding_model, now, now,
            )  # fmt: skip
            continue
        for c in result.chunks:
            yield (
                c.id, c.content_id, c.version_number, c.ordinal, list(c.section_path), c.text,
                len(c.text.split()), c.start_offset, c.end_offset, c.id, worker.embedding_model,
                now, now,
            )  # fmt: skip
    worker.flush()


@dataclass
class ReindexStats:
    items: int
    chunks: int
    failures: list[tuple[str, int, str]]  # (content_id, version, error)


def run(
    spark: Any,
    factory: WorkerFactory = default_worker,
    *,
    content_ids: list[str] | None = None,
    write_chunks: bool = True,
    slices: int = 8,
) -> ReindexStats:
    versions = spark.sql(CURRENT_VERSIONS)
    if content_ids:
        versions = versions.where(versions.content_id.isin(content_ids))
    items = versions.collect()
    if not items:
        return ReindexStats(0, 0, [])
    rdd = spark.sparkContext.parallelize(
        [r.asDict() for r in items], min(slices, len(items))
    ).mapPartitions(lambda rows: sync_partition(rows, factory))
    rows = spark.createDataFrame(rdd, CHUNK_COLUMNS).cache()  # the sync runs exactly once
    failed = rows.where("chunk_id IS NULL").select("content_id", "version", "text").collect()
    failures = [(r.content_id, r.version, r.text) for r in failed]
    failed_keys = {(content, version) for content, version, _ in failures}
    done = [r for r in items if (r["content_id"], r["version"]) not in failed_keys]
    chunks = rows.where("chunk_id IS NOT NULL")
    count = chunks.count()
    if write_chunks and done:
        processed = ", ".join(f"('{_q(r['content_id'])}', {int(r['version'])})" for r in done)
        spark.sql(f"DELETE FROM silver.content_chunks WHERE (content_id, version) IN ({processed})")
        chunks.writeTo("silver.content_chunks").append()
    rows.unpersist()
    return ReindexStats(len(done), count, failures)


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def main(content_id: list[str] | None = None, write_chunks: bool = True) -> None:
    import typer

    from edu_platform.platform.batch.spark_session import build_spark
    from edu_platform.platform.config import get_settings

    spark = build_spark("edu-content-reindex", get_settings())
    stats = run(spark, content_ids=content_id, write_chunks=write_chunks)
    typer.echo(f"reindexed {stats.items} content item(s), {stats.chunks} chunk(s)")
    for content, version, error in stats.failures:
        typer.echo(f"FAILED {content} v{version}: {error}", err=True)
    if stats.failures:
        raise typer.Exit(1)
