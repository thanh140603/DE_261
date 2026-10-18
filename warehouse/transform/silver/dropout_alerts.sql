-- silver.dropout_alerts <- bronze.domain_events (topic risk.dropout_alert.v1, DropoutRiskDetected).
MERGE INTO silver.dropout_alerts AS t
USING (
  SELECT e.event_id AS alert_id, pseudonymize(e.learner_id) AS learner_pseudonym, e.course_id,
         e.score AS risk_score, e.top_signals, CAST(e.occurred_at AS TIMESTAMP) AS alerted_at,
         ingest_date AS _ingest_date
  FROM (
    SELECT from_json(payload, 'event_id STRING, occurred_at STRING, learner_id STRING, course_id STRING, score DOUBLE, top_signals ARRAY<STRING>') AS e,
           ingest_date,
           row_number() OVER (PARTITION BY get_json_object(payload, '$.event_id') ORDER BY kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND e.event_id IS NOT NULL AND e.learner_id IS NOT NULL
) AS s
ON t.alert_id = s.alert_id
WHEN NOT MATCHED THEN INSERT
  (alert_id, learner_pseudonym, course_id, risk_score, top_signals, alerted_at, _ingest_date, _processed_at)
  VALUES (s.alert_id, s.learner_pseudonym, s.course_id, s.risk_score, s.top_signals, s.alerted_at,
          s._ingest_date, current_timestamp());
