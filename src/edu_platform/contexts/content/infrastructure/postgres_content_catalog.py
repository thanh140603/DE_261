"""ContentCatalog adapter on the LMS PostgreSQL ``public.course_content`` table.

``publish_version`` holds a row lock (SELECT ... FOR UPDATE) while the document is written,
so two concurrent publishers get consecutive versions and the committed row always points
at an object that exists. If the commit fails after the write, the orphan object is
harmless: it is never referenced and the retry overwrites the same key.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.rows import dict_row

from edu_platform.contexts.content.application.ports import CatalogEntry

_COLUMNS = (
    "content_id, course_id, content_type, title, version, object_key, duration_sec, updated_at"
)


class PostgresContentCatalog:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def get(self, content_id: str) -> CatalogEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM public.course_content WHERE content_id = %s",
                (content_id,),
            ).fetchone()
        return None if row is None else CatalogEntry(**row)

    def for_course(self, course_id: str) -> list[CatalogEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM public.course_content WHERE course_id = %s "
                "ORDER BY title, content_id",
                (course_id,),
            ).fetchall()
        return [CatalogEntry(**r) for r in rows]

    def all_entries(self) -> list[CatalogEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM public.course_content ORDER BY course_id, content_id"
            ).fetchall()
        return [CatalogEntry(**r) for r in rows]

    def publish_version(
        self, content_id: str, title: str | None, write: Callable[[str, int], str]
    ) -> CatalogEntry:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT course_id, version FROM public.course_content WHERE content_id = %s "
                "FOR UPDATE",
                (content_id,),
            ).fetchone()
            if row is None:
                raise KeyError(content_id)
            version = int(row["version"]) + 1
            object_key = write(row["course_id"], version)
            updated = conn.execute(
                "UPDATE public.course_content SET version = %s, object_key = %s, "
                "title = coalesce(%s, title), updated_at = now() WHERE content_id = %s "
                f"RETURNING {_COLUMNS}",
                (version, object_key, title, content_id),
            ).fetchone()
        assert updated is not None
        return CatalogEntry(**updated)
