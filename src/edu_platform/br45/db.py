from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings

Db = psycopg.Connection[dict[str, Any]]

ROOT = Path(__file__).resolve().parents[3]


@contextmanager
def connect(dsn: str | None = None) -> Iterator[Db]:
    with psycopg.connect(dsn or settings().dsn, row_factory=dict_row) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        yield conn


def migrate(dsn: str | None = None) -> None:
    with connect(dsn) as conn:
        conn.execute((ROOT / "infra/postgres/br45.sql").read_text())


def state(conn: Db, key: str, value: Any = None) -> Any:
    if value is not None:
        conn.execute(
            (
                "INSERT INTO analytics.pipeline_state(key,value) VALUES(%s,%s) ON "
                "CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=now()"
            ),
            (key, Jsonb(value)),
        )
        return value
    row = conn.execute("SELECT value FROM analytics.pipeline_state WHERE key=%s", (key,)).fetchone()
    return row["value"] if row else None


def clean(conn: Db, table: str) -> list[dict[str, Any]]:
    return [
        r["data"]
        for r in conn.execute(
            (
                "SELECT data FROM analytics.clean_rows WHERE table_name=%s AND NOT deleted "
                "ORDER BY row_key"
            ),
            (table,),
        )
    ]
