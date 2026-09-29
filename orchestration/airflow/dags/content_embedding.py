"""DAG content_embedding - corpus chunking + embedding. Schedule: every 6 h + on-demand trigger.

Content (TODO):
- task chunk_and_embed: edu batch content-chunking-embedding --run-date {{ ds }}
- task reindex_search: bulk refresh OpenSearch aliases (blue/green).
"""

# TODO: from airflow import DAG / Dataset; define tasks as described above.
