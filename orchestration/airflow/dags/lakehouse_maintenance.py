"""DAG lakehouse_maintenance - retention / OPTIMIZE (Z-order) / VACUUM. Schedule: daily 04:00.

Policies come from table properties declared in warehouse/ddl (edu.retention_days, edu.zorder).
"""

from __future__ import annotations

from _common import DEFAULT_ARGS, START, edu_task
from airflow import DAG

with DAG(
    dag_id="lakehouse_maintenance",
    description="Bronze PII retention, small-file compaction, vacuum",
    schedule="0 4 * * *",
    start_date=START,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["lakehouse", "ops"],
) as dag:
    edu_task("maintenance", "batch lakehouse-maintenance --run-date {{ ds }}")
