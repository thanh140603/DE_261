"""DAG analytics_marts_daily - BR4 / BR6 / BR7 marts. Schedule: daily 02:00 UTC.

{{ ds }} is the previous (closed) day, so each mart's as_of_date partition describes a complete
day. Dashboards and the API read the marts through Trino (lakehouse.mart.*).
"""

from __future__ import annotations

from _common import DEFAULT_ARGS, MARTS, START, edu_task
from airflow import DAG

with DAG(
    dag_id="analytics_marts_daily",
    description="Instructor / admin marts: assessment anomalies, org progress, video heatmap",
    schedule="0 2 * * *",
    start_date=START,
    catchup=True,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["lakehouse", "BR4", "BR6", "BR7"],
) as dag:
    gold = edu_task("gold_refresh", "warehouse run --run-date {{ ds }} --layer gold")
    marts = [
        edu_task(
            name.split(".")[1],
            f"warehouse run --run-date {{{{ ds }}}} --select {name}",
            outlets=[MARTS],
        )
        for name in ("mart.assessment_item_stats", "mart.org_progress", "mart.video_heatmap")
    ]
    gold >> marts
