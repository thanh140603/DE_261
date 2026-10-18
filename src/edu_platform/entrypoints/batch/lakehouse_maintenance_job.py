"""Spark job: lakehouse_maintenance_job (ops, daily 04:00 - orchestration/airflow/dags).

For every lakehouse table:
1. retention   bronze tables with ``edu.retention_days`` lose rows past the window (ADR 0007:
               raw identifiers are kept only as long as replay needs them);
2. compaction  OPTIMIZE, Z-ordered by ``edu.zorder`` when declared;
3. vacuum      remove unreferenced files older than 7 days (= time-travel horizon).
Policies are table properties set in warehouse/ddl. Idempotent; safe to rerun.
"""

from __future__ import annotations

from datetime import date

import typer

from edu_platform.platform.batch import delta_tables
from edu_platform.platform.batch.spark_session import build_spark
from edu_platform.platform.config import get_settings
from edu_platform.platform.logging import get_logger

log = get_logger(__name__)


def main(
    run_date: str = typer.Option(..., help="Logical date (YYYY-MM-DD)"),
    vacuum: bool = typer.Option(True, help="Run VACUUM after compaction"),
) -> None:
    """Retention, compaction and vacuum for every table in the lakehouse schemas."""
    spark = build_spark("edu-lakehouse-maintenance", get_settings())
    as_of = date.fromisoformat(run_date)
    for table in delta_tables.list_tables(spark):
        props = delta_tables.table_properties(spark, table)
        if "edu.retention_days" in props:
            delta_tables.purge_older_than(
                spark, table, "ingest_date", int(props["edu.retention_days"]), as_of
            )
        zorder = [c.strip() for c in props.get("edu.zorder", "").split(",") if c.strip()]
        delta_tables.optimize(spark, table, zorder or None)
        if vacuum:
            delta_tables.vacuum(spark, table)
        log.info("table maintained", table=table, zorder=zorder or None)


if __name__ == "__main__":
    typer.run(main)
