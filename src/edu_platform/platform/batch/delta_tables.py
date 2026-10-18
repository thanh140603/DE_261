"""Delta table maintenance helpers (used by entrypoints/batch/lakehouse_maintenance_job.py).

Writes themselves are SQL (warehouse/transform) run by the warehouse runner; these helpers
cover the table-level operations around them. Policies live on the tables as properties
declared in warehouse/ddl, so a new table is maintained without touching this code:
- ``edu.retention_days``  bronze PII minimisation: rows older than N days are deleted
- ``edu.zorder``          comma-separated columns to Z-order by when compacting
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

LAKEHOUSE_SCHEMAS = ("bronze", "silver", "gold", "mart", "features", "ops")
DEFAULT_VACUUM_HOURS = 168  # Delta's minimum safe retention; time travel window = 7 days


def list_tables(spark: Any, schemas: tuple[str, ...] = LAKEHOUSE_SCHEMAS) -> list[str]:
    return [
        f"{schema}.{row['tableName']}"
        for schema in schemas
        for row in spark.sql(f"SHOW TABLES IN {schema}").collect()
        if not row["isTemporary"]
    ]


def table_properties(spark: Any, table: str) -> dict[str, str]:
    return {r["key"]: r["value"] for r in spark.sql(f"SHOW TBLPROPERTIES {table}").collect()}


def latest_version(spark: Any, table: str) -> int:
    return int(spark.sql(f"DESCRIBE HISTORY {table} LIMIT 1").collect()[0]["version"])


def purge_older_than(spark: Any, table: str, column: str, keep_days: int, as_of: date) -> None:
    """Delete rows whose ``column`` date is older than the retention window."""
    cutoff = as_of - timedelta(days=keep_days)
    spark.sql(f"DELETE FROM {table} WHERE {column} < DATE'{cutoff.isoformat()}'")


def optimize(spark: Any, table: str, zorder_by: list[str] | None = None) -> None:
    """Compact small files (streaming writers create many); Z-order for data skipping."""
    zorder = f" ZORDER BY ({', '.join(zorder_by)})" if zorder_by else ""
    spark.sql(f"OPTIMIZE {table}{zorder}")


def vacuum(spark: Any, table: str, retention_hours: int = DEFAULT_VACUUM_HOURS) -> None:
    """Physically remove files no longer referenced for longer than the retention window."""
    spark.sql(f"VACUUM {table} RETAIN {retention_hours} HOURS")
