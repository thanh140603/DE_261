"""DAG content_embedding - BR8 corpus re-chunk / re-embed / re-index. Every 6 h + manual trigger.

The content-sync service is the primary path: every publish reaches OpenSearch within about a
second through CDC (ADR 0013). This DAG is the safety net and the bulk path: it rebuilds
silver.content_versions from the CDC history in bronze, then re-indexes the current version
of every content item, e.g. after a chunking or embedding change, after restoring OpenSearch,
or when the service was down. Both steps are idempotent (deterministic chunk ids), so a rerun
or a manual trigger is safe.

  content_versions -> reindex      (reindex exits non-zero listing items that failed)

Needs the br678 services (OpenSearch, Redis, MinIO corpus) in addition to the lakehouse.
"""

from __future__ import annotations

from _common import DEFAULT_ARGS, START, edu_task
from airflow import DAG

with DAG(
    dag_id="content_embedding",
    description="Re-chunk, re-embed and re-index current content versions (OpenSearch, Redis)",
    schedule="0 */6 * * *",
    start_date=START,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["content", "search", "BR8"],
) as dag:
    versions = edu_task(
        "content_versions",
        "warehouse run --run-date {{ ds }} --select silver.content_versions",
    )
    reindex = edu_task("reindex", "batch content-reindex")
    versions >> reindex
