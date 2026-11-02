"""PostgresContentCatalog against the LMS database (public.course_content).

  docker compose up -d postgres
  uv run pytest -m integration tests/integration/test_postgres_content_catalog.py

Works on its own throwaway row, deleted afterwards.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator

import psycopg
import pytest

from edu_platform.contexts.content.infrastructure.postgres_content_catalog import (
    PostgresContentCatalog,
)

pytestmark = pytest.mark.integration
DSN = os.getenv("EDU_POSTGRES_DSN", "postgresql://lms:lms@localhost:5433/lms")


@pytest.fixture
def content_id() -> Iterator[str]:
    cid = f"v-test-{uuid.uuid4().hex[:8]}"
    try:
        conn = psycopg.connect(DSN, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip(f"PostgreSQL not reachable at {DSN}")
    with conn:
        conn.execute(
            "INSERT INTO public.course_content (content_id, course_id, content_type, title, "
            "version, object_key, duration_sec) VALUES (%s, 'c-sql-101', 'video_transcript', "
            "'Test video', 1, %s, 60)",
            (cid, f"courses/c-sql-101/{cid}/v1.vtt"),
        )
    yield cid
    with psycopg.connect(DSN) as conn:
        conn.execute("DELETE FROM public.course_content WHERE content_id = %s", (cid,))


def test_get_and_list(content_id: str) -> None:
    catalog = PostgresContentCatalog(DSN)
    entry = catalog.get(content_id)
    assert entry is not None and entry.version == 1 and entry.updated_at.tzinfo is not None
    assert content_id in {e.content_id for e in catalog.for_course("c-sql-101")}
    assert content_id in {e.content_id for e in catalog.all_entries()}
    assert catalog.get("v-does-not-exist") is None


def test_concurrent_publishers_get_consecutive_versions(content_id: str) -> None:
    catalog = PostgresContentCatalog(DSN)
    written: list[tuple[str, int]] = []
    lock = threading.Lock()

    def write(course_id: str, version: int) -> str:
        with lock:
            written.append((course_id, version))
        return f"courses/{course_id}/{content_id}/v{version}.md"

    threads = [
        threading.Thread(target=catalog.publish_version, args=(content_id, None, write))
        for _ in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(v for _, v in written) == [2, 3, 4, 5, 6]  # no version handed out twice
    entry = catalog.get(content_id)
    assert entry is not None and entry.version == 6
    assert entry.object_key == f"courses/c-sql-101/{content_id}/v6.md"


def test_failed_write_rolls_back(content_id: str) -> None:
    catalog = PostgresContentCatalog(DSN)

    def broken(course_id: str, version: int) -> str:
        raise OSError("object storage down")

    with pytest.raises(OSError):
        catalog.publish_version(content_id, "New title", broken)
    entry = catalog.get(content_id)
    assert entry is not None and (entry.version, entry.title) == (1, "Test video")
    with pytest.raises(KeyError):
        catalog.publish_version("v-does-not-exist", None, broken)
