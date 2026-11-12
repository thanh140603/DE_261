"""Stage a replacement BR45 source database from the authoritative PostgreSQL rows."""

from __future__ import annotations

import re
from typing import Any

from psycopg import sql

from .contracts import CONTRACTS
from .db import Db, apply_migrations, connect


def transfer(source: Db, target: Db, table: sql.Identifier) -> int:
    if target.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(table)).fetchone():
        raise ValueError(f"Replacement table already contains data: {table!s}")
    with (
        source.cursor().copy(sql.SQL("COPY {} TO STDOUT").format(table)) as outgoing,
        target.cursor().copy(sql.SQL("COPY {} FROM STDIN").format(table)) as incoming,
    ):
        for block in outgoing:
            incoming.write(block)
    count = sql.SQL("SELECT count(*) AS total FROM {}").format(table)
    before, after = source.execute(count).fetchone(), target.execute(count).fetchone()
    assert before is not None and after is not None
    if before["total"] != after["total"]:
        raise RuntimeError(f"Row count diverged while copying {table!s}")
    return int(after["total"])


def stage(source_dsn: str, target_dsn: str) -> dict[str, Any]:
    """Copy one consistent source snapshot. Analytics are rebuilt by a fresh connector."""
    with connect(source_dsn) as source, connect(target_dsn) as target:
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        source_name = source.info.dbname
        target_name = target.info.dbname
        if target_name == source_name or not re.fullmatch(r"br45_rebuild_[a-z0-9_]+", target_name):
            raise ValueError("Use a separate empty database named br45_rebuild_<run>")
        if source_name == "br45_classroom":
            raise ValueError("This rebuild command targets the persistent BR45 runtime")
        target.execute("SELECT pg_advisory_xact_lock(hashtext('br45-migrations'))")
        schemas = target.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname IN ('br45','analytics','classroom')"
        ).fetchone()
        if schemas:
            raise ValueError("Use a fresh replacement database without BR45 schemas")
        apply_migrations(target, classroom=False)
        counts = {
            table: transfer(source, target, sql.Identifier("br45", table)) for table in CONTRACTS
        }
        for table in ("course_policies", "risk_history", "dropout_alerts", "intervention_notes"):
            counts[table] = transfer(source, target, sql.Identifier("analytics", table))
        target.execute(
            "SELECT setval(pg_get_serial_sequence('analytics.intervention_notes','id'),"
            "coalesce(max(id),1),max(id) IS NOT NULL) FROM analytics.intervention_notes"
        )
        return {
            "replacement_database": target_name,
            "verified_source_row_counts": counts,
            "next_step": "Run the isolated connector, topics, and checkpoints before cutover.",
        }
