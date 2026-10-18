"""DAG engagement_weekly - BR8 engagement trend. Schedule: weekly, Monday 02:00 UTC.

{{ ds }} is the Monday of the closed week; the mart holds the last 4 weekly windows ending at
that date with the declining-trend flag (EngagementPolicy).
"""

from __future__ import annotations

from _common import DEFAULT_ARGS, MARTS, START, edu_task
from airflow import DAG

with DAG(
    dag_id="engagement_weekly",
    description="Weekly engagement score per learner/course and declining-trend detection",
    schedule="0 2 * * 1",
    start_date=START,
    catchup=True,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["lakehouse", "BR8"],
) as dag:
    edu_task(
        "engagement_trend",
        "warehouse run --run-date {{ ds }} --select mart.engagement_trend",
        outlets=[MARTS],
    )
