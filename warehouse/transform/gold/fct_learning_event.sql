-- gold.fct_learning_event (window: event_date in [window_start, window_end]).
-- Re-deriving the window picks up late mobile events and late-arriving dimension rows.
-- SCD2 keys are resolved as of occurred_at; SCD1 keys are deterministic hashes
-- (integrity checked by quality/gold_orphan_keys.sql).
INSERT INTO gold.fct_learning_event
REPLACE WHERE event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
SELECT e.event_id, e.event_date, CAST(date_format(e.event_date, 'yyyyMMdd') AS INT) AS date_key,
       coalesce(l.learner_key, -1) AS learner_key,
       xxhash64(e.course_id) AS course_key,
       coalesce(c.content_key, -1) AS content_key,
       xxhash64(e.verb) AS activity_key,
       e.learner_pseudonym, e.course_id, e.content_id, e.verb, e.session_id, e.platform,
       e.occurred_at, e.received_at, e.video_position_sec, e.is_late, e.lateness_sec,
       current_timestamp() AS _built_at
FROM silver.learning_events e
LEFT JOIN gold.dim_learner l
  ON l.learner_pseudonym = e.learner_pseudonym
 AND e.occurred_at >= l.valid_from AND e.occurred_at < l.valid_to
LEFT JOIN gold.dim_content c
  ON c.content_id = e.content_id
 AND e.occurred_at >= c.valid_from AND e.occurred_at < c.valid_to
WHERE e.event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}';
