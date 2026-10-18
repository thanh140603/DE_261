"""DAG medallion_daily - bronze -> silver -> gold (BR6 medallion). Schedule: hourly.

The streaming job (`edu stream lakehouse-landing`) keeps bronze/silver fresh within minutes;
this DAG reconciles silver from the bronze window (catches anything the stream skipped) and
rebuilds the dimensional model. Gold windows reach back further on their own when silver
received late events (models.yaml `late_data`), so no separate late-data sweep is needed.

  silver_reconcile -> gold   (each layer stops on a failed `error` quality gate)
"""

from __future__ import annotations

from _common import DEFAULT_ARGS, GOLD, SILVER, START, edu_task
from airflow import DAG

with DAG(
    dag_id="medallion_daily",
    description="Lakehouse medallion: silver reconcile + gold dimensional model",
    schedule="@hourly",
    start_date=START,
    catchup=False,
    max_active_runs=1,  # gold builds of overlapping windows must not interleave
    default_args=DEFAULT_ARGS,
    tags=["lakehouse", "BR6"],
) as dag:
    silver = edu_task(
        "silver_reconcile",
        "warehouse run --run-date {{ ds }} --layer silver",
        outlets=[SILVER],
    )
    gold = edu_task("gold", "warehouse run --run-date {{ ds }} --layer gold", outlets=[GOLD])
    silver >> gold
