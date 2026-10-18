"""Shared DAG helpers. Tasks only shell out to the `edu` CLI; all logic lives in the package.

Local: the Airflow worker image is built FROM de261/spark:local (edu CLI + Spark + Delta jars)
and runs BashOperator. Prod: swap edu_task for KubernetesPodOperator with the same command.
Every command is idempotent on {{ ds }}, so retries and `airflow dags backfill` are safe.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.datasets import Dataset
from airflow.operators.bash import BashOperator

START = pendulum.datetime(2026, 9, 1, tz="UTC")
DEFAULT_ARGS = {
    "owner": "data-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(hours=2),
}

# Data-aware scheduling: producers declare outlets, consumers schedule on them.
SILVER = Dataset("lakehouse://silver")
GOLD = Dataset("lakehouse://gold")
MARTS = Dataset("lakehouse://mart")


def edu_task(task_id: str, command: str, **kwargs: object) -> BashOperator:
    return BashOperator(task_id=task_id, bash_command=f"edu {command}", **kwargs)
