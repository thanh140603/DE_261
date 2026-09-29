"""DAG features_daily - batch feature branch (BR2). Triggered by silver dataset.

Content (TODO):
- task batch_features: edu batch batch-features --run-date {{ ds }}
- task materialize_online: part of the same job; verify Redis row count vs offline.
"""

# TODO: from airflow import DAG / Dataset; define tasks as described above.
