"""Spark job: content_chunking_embedding_job (corpus pipeline).

Content (TODO):
- For ContentVersionPublished events since last run: ChunkAndEmbedContent per document.
- Parallelise across executors; batch embedding calls; write silver.content_chunks.
Wiring: platform.batch.spark_session.build_spark -> Delta readers/writers -> context use case.
Idempotent per (run_date) partition so Airflow retries/backfills are safe.
"""

from __future__ import annotations

import typer


def main(run_date: str = typer.Option(..., help="Partition to process, YYYY-MM-DD")) -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    typer.run(main)
