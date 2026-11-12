# Orchestration (Airflow)

Batch pipelines are scheduled here. Streaming jobs and services (lakehouse landing, br45
stream, telemetry-live, content-sync) are long-running workloads, not DAG tasks.

Conventions
- One DAG per business cadence, tasks call the `edu` CLI via `BashOperator` (local) or
  `KubernetesPodOperator` (prod) with the same command.
- Every task is idempotent on `{{ ds }}` so retries and `airflow dags backfill` are safe.
- Dataset-aware scheduling: `medallion_daily` publishes `lakehouse://silver` and
  `lakehouse://gold`; `features_daily` runs when gold is refreshed.

| DAG | Schedule | Tasks (`edu ...`) | BR |
|-----|----------|-------------------|----|
| `medallion_daily` | hourly | `warehouse run --layer silver` -> `--layer gold` | BR6 |
| `analytics_marts_daily` | 02:00 daily, catchup | gold refresh -> `mart.assessment_item_stats`, `mart.org_progress`, `mart.video_heatmap` | BR4, BR6, BR7 |
| `engagement_weekly` | Monday 02:00, catchup | `mart.engagement_trend` | BR8 |
| `features_daily` | on gold refresh | `warehouse run --layer features` | BR2 |
| `content_embedding` | every 6 h + manual | `silver.content_versions` -> `batch content-reindex` | BR8 |
| `lakehouse_maintenance` | 04:00 daily | `batch lakehouse-maintenance` (retention, OPTIMIZE, VACUUM) | ops |

## Run locally (docker compose profile `airflow`)

```bash
docker compose build spark                     # de261/airflow is built FROM de261/spark
docker compose --profile airflow up -d --build airflow-webserver airflow-scheduler
open http://localhost:8088                     # admin / admin
```

- Image `infra/airflow/Dockerfile`: Airflow 2.10 in its own virtualenv on top of the Spark
  image, so tasks run `edu` with the same Spark 3.5 + Delta + S3A runtime as `spark-jobs`
  and Spark stays the only Delta writer (ADR 0011). `./src`, `./warehouse` and the DAGs are
  mounted, so code and model edits apply without a rebuild.
- `LocalExecutor` with metadata in `airflow-db` (Postgres 16). The scheduler runs the tasks.
- DAGs start paused. `default_pool` has one slot, so one Spark job runs at a time and the
  stack fits an 8 GB Docker VM. Raise `AIRFLOW__CORE__DEFAULT_POOL_TASK_SLOT_COUNT` on a bigger
  machine.
- `analytics_marts_daily` and `engagement_weekly` use `catchup=True` from 2026-09-01: unpausing
  them queues every missed day. For a demo, trigger or backfill a short range instead:
  `docker compose exec airflow-scheduler airflow dags backfill analytics_marts_daily -s 2026-10-10 -e 2026-10-17`.
- `content_embedding` also needs the br678 services (OpenSearch, Redis, corpus in MinIO).
- Overrides: `AIRFLOW_PORT`, `AIRFLOW_ADMIN_USER`, `AIRFLOW_ADMIN_PASSWORD`, `AIRFLOW_SECRET_KEY`.

Test one task without the scheduler:

```bash
docker compose exec airflow-scheduler airflow tasks test medallion_daily silver_reconcile 2026-10-17
```
