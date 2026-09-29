# Orchestration (Airflow)

Batch pipelines are scheduled here. Streaming jobs (Flink) and services are
deployed as long-running workloads (Kubernetes), not as DAG tasks - Airflow only
monitors them.

Conventions
- One DAG per business cadence, tasks call the `edu batch <job>` CLI via
  `KubernetesPodOperator` (prod) or `BashOperator` (local).
- Every task is idempotent on `{{ ds }}` so `airflow dags backfill` is safe.
- Dataset-aware scheduling: silver DAG publishes `Dataset("delta://silver/learning_events")`
  and gold/feature DAGs are triggered by it.
