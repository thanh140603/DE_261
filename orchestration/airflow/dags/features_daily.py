"""DAG features_daily - batch feature branch (BR2). Triggered when gold is refreshed.

features.learner_longterm is written per as_of_date (point-in-time training sets). Online
materialisation to Redis is the batch_features_job (TODO) and runs after the offline write.
"""

from __future__ import annotations

from _common import DEFAULT_ARGS, GOLD, START, edu_task
from airflow import DAG

with DAG(
    dag_id="features_daily",
    description="Offline feature store learner_longterm (+ Redis materialisation)",
    schedule=[GOLD],
    start_date=START,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["lakehouse", "features", "BR2"],
) as dag:
    edu_task(
        "learner_longterm",
        "warehouse run --run-date {{ data_interval_end | ds }} --layer features",
    )
