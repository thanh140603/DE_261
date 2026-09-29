"""DAG medallion_daily - bronze -> silver for telemetry + CDC (BR6). Schedule: hourly.

Content (TODO):
- task bronze_to_silver: edu batch bronze-to-silver --run-date {{ ds }}
- task data_quality: Great Expectations / Deequ checks on silver.learning_events
  (no PII columns, event_id unique, lateness distribution).
- outlets: Dataset('delta://silver/learning_events')
"""

# TODO: from airflow import DAG / Dataset; define tasks as described above.
