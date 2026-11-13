MERGE INTO silver.dropout_alert_transitions AS target
USING (
  SELECT e.event_id AS transition_id, e.alert_id, pseudonymize(e.learner_id) AS learner_pseudonym,
         e.course_id, e.status, e.policy_version, CAST(e.occurred_at AS TIMESTAMP) AS occurred_at,
         ingest_date AS _ingest_date
  FROM (
    SELECT from_json(payload, 'event_id STRING, alert_id STRING, learner_id STRING, course_id STRING, status STRING, policy_version INT, occurred_at STRING') AS e,
           ingest_date,
           row_number() OVER (
             PARTITION BY get_json_object(payload, '$.event_id') ORDER BY kafka_offset DESC
           ) AS rn
    FROM _src
  ) WHERE rn = 1 AND e.event_id IS NOT NULL AND e.alert_id IS NOT NULL AND e.learner_id IS NOT NULL
    AND e.course_id IS NOT NULL AND e.policy_version > 0 AND e.occurred_at IS NOT NULL
    AND e.status IN ('NEW','ACKNOWLEDGED','RESOLVED')
) AS source
ON target.transition_id = source.transition_id
WHEN NOT MATCHED THEN INSERT
  (transition_id, alert_id, learner_pseudonym, course_id, status, policy_version, occurred_at, _ingest_date, _processed_at)
  VALUES (source.transition_id, source.alert_id, source.learner_pseudonym, source.course_id,
          source.status, source.policy_version, source.occurred_at, source._ingest_date, current_timestamp());
