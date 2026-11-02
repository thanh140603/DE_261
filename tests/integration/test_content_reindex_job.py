"""content_chunking_embedding_job on real Delta tables (warehouse/ddl) with S3 served by a
local moto server, so the Spark Python workers (separate processes) read real objects.

  uv run pytest -m spark tests/integration/test_content_reindex_job.py
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from edu_platform.entrypoints.batch.content_chunking_embedding_job import Worker, run
from edu_platform.platform.warehouse.sql import render, split_statements

pytestmark = pytest.mark.spark
DDL = Path(__file__).resolve().parents[2] / "warehouse" / "ddl"
JOINS_V1 = "# Joins\n\nAn inner join keeps only matching rows."
JOINS_V2 = "# Joins\n\nA left join keeps every row.\n\n# Outer joins\n\nUnmatched columns are NULL."
FUNC_V1 = "# Functions\n\nA function packages logic under a name."


@pytest.fixture(scope="module")
def s3_endpoint() -> Iterator[str]:
    boto3 = pytest.importorskip("boto3")
    server_mod = pytest.importorskip("moto.server")
    server = server_mod.ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    s3 = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1",
                      aws_access_key_id="test", aws_secret_access_key="test")  # fmt: skip
    s3.create_bucket(Bucket="corpus")
    for key, body in {
        "courses/c-sql-101/v-sql-joins/v1.vtt": JOINS_V1,
        "courses/c-sql-101/v-sql-joins/v2.md": JOINS_V2,
        "courses/c-py-201/v-py-func/v1.vtt": FUNC_V1,
    }.items():
        s3.put_object(Bucket="corpus", Key=key, Body=body.encode())
    yield endpoint
    server.stop()


@pytest.fixture(scope="module")
def spark(spark_session: Any, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    session = spark_session
    root = tmp_path_factory.mktemp("lake")
    params = {"lakehouse_root": f"file://{root}"}
    for name in ("00_schemas.sql", "20_silver.sql"):
        for statement in split_statements(render((DDL / name).read_text("utf-8"), params)):
            session.sql(statement)
    session.sql("""INSERT INTO silver.content_versions VALUES
      ('v-sql-joins', 1, 'c-sql-101', 'video_transcript', 'Joins',
       'courses/c-sql-101/v-sql-joins/v1.vtt', 420, TIMESTAMP'2026-09-01 07:00:00',
       TIMESTAMP'2026-09-01 07:00:00', false, 100, current_timestamp()),
      ('v-sql-joins', 2, 'c-sql-101', 'video_transcript', 'Joins (re-recorded)',
       'courses/c-sql-101/v-sql-joins/v2.md', 390, TIMESTAMP'2026-10-08 07:00:00',
       TIMESTAMP'2026-10-08 07:00:00', false, 200, current_timestamp()),
      ('v-py-func', 1, 'c-py-201', 'video_transcript', 'Functions',
       'courses/c-py-201/v-py-func/v1.vtt', 300, TIMESTAMP'2026-09-01 07:00:00',
       TIMESTAMP'2026-09-01 07:00:00', false, 300, current_timestamp()),
      ('v-missing', 1, 'c-py-201', 'video_transcript', 'No object uploaded',
       'courses/c-py-201/v-missing/v1.vtt', 60, TIMESTAMP'2026-09-01 07:00:00',
       TIMESTAMP'2026-09-01 07:00:00', false, 350, current_timestamp()),
      ('v-gone', 1, 'c-py-201', 'video_transcript', 'Removed lesson',
       'courses/c-py-201/v-gone/v1.vtt', 60, TIMESTAMP'2026-09-01 07:00:00',
       TIMESTAMP'2026-09-02 07:00:00', true, 400, current_timestamp())""")
    yield session
    for schema in ("bronze", "silver", "gold", "mart", "features", "ops"):
        session.sql(f"DROP DATABASE IF EXISTS {schema} CASCADE")


def factory(endpoint: str) -> Any:
    """Pickled into the Spark tasks: real S3 adapter (moto server) + in-memory index/cache."""

    def build() -> Worker:
        import boto3

        from edu_platform.contexts.content.application.sync_content_change import (
            SyncContentChange,
        )
        from edu_platform.contexts.content.infrastructure.in_memory import (
            InMemoryCacheInvalidator,
            InMemorySearchIndexer,
            InMemoryVectorIndex,
        )
        from edu_platform.contexts.content.infrastructure.s3_document_store import (
            S3DocumentStore,
        )

        class Events:
            def publish(self, events: list[Any], *, topic: str | None = None) -> None:
                pass

        s3 = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1",
                          aws_access_key_id="test", aws_secret_access_key="test")  # fmt: skip
        vectors = InMemoryVectorIndex()
        sync = SyncContentChange(
            S3DocumentStore(s3, "corpus"),
            InMemoryCacheInvalidator(),
            vectors,
            InMemorySearchIndexer(),
            Events(),
        )
        return Worker(sync, lambda: None, "hashing-v1-256")

    return build


def chunk_rows(spark: Any) -> list[Any]:
    return spark.sql(
        "SELECT content_id, version, ordinal, section_path, text, embedding_model "
        "FROM silver.content_chunks ORDER BY content_id, ordinal"
    ).collect()


def test_reindex_writes_chunks_of_current_versions(spark: Any, s3_endpoint: str) -> None:
    stats = run(spark, factory(s3_endpoint), slices=2)
    assert stats.items == 2  # v-gone is deleted, v-sql-joins only once (v2)
    # one missing object fails that item only; the others are still reindexed
    assert [(c, v) for c, v, _ in stats.failures] == [("v-missing", 1)]
    assert "DocumentNotFound" in stats.failures[0][2]
    rows = chunk_rows(spark)
    assert {(r.content_id, r.version) for r in rows} == {("v-py-func", 1), ("v-sql-joins", 2)}
    joins = [r for r in rows if r.content_id == "v-sql-joins"]
    assert [list(r.section_path) for r in joins] == [["Joins"], ["Outer joins"]]
    assert "left join" in joins[0].text and all(r.embedding_model == "hashing-v1-256" for r in rows)
    assert stats.chunks == len(rows)


def test_rerun_is_idempotent_and_selection_works(spark: Any, s3_endpoint: str) -> None:
    run(spark, factory(s3_endpoint))
    before = chunk_rows(spark)
    run(spark, factory(s3_endpoint))
    assert chunk_rows(spark) == before
    stats = run(spark, factory(s3_endpoint), content_ids=["v-py-func"])
    assert stats.items == 1 and stats.failures == []
    assert chunk_rows(spark) == before
    empty = run(spark, factory(s3_endpoint), content_ids=["v-unknown"])
    assert (empty.items, empty.chunks, empty.failures) == (0, 0, [])
