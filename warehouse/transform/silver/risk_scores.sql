-- silver.risk_scores <- bronze.domain_events (topic risk.learner_score.v1, emitted by the Flink
-- dropout_risk_job after every rescore; contract schemas/risk/v1/learner_score.schema.json).
MERGE INTO silver.risk_scores AS t
USING (
  SELECT e.event_id AS score_event_id, pseudonymize(e.learner_id) AS learner_pseudonym, e.course_id,
         e.score AS risk_score, CAST(e.computed_at AS TIMESTAMP) AS computed_at,
         CAST(CAST(e.computed_at AS TIMESTAMP) AS DATE) AS score_date, ingest_date AS _ingest_date
  FROM (
    SELECT from_json(payload, 'event_id STRING, learner_id STRING, course_id STRING, score DOUBLE, computed_at STRING') AS e,
           ingest_date,
           row_number() OVER (PARTITION BY get_json_object(payload, '$.event_id') ORDER BY kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND e.event_id IS NOT NULL AND e.learner_id IS NOT NULL AND e.score IS NOT NULL
) AS s
ON t.score_event_id = s.score_event_id AND t.score_date = s.score_date
WHEN NOT MATCHED THEN INSERT
  (score_event_id, learner_pseudonym, course_id, risk_score, computed_at, score_date, _ingest_date, _processed_at)
  VALUES (s.score_event_id, s.learner_pseudonym, s.course_id, s.risk_score, s.computed_at, s.score_date,
          s._ingest_date, current_timestamp());
