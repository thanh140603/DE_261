-- silver.lesson_progress <- bronze.cdc_events (source_table = 'lesson_progress').
-- Milestones: first_progress_at (first change seen), completed_at (first time 100 %).
MERGE INTO silver.lesson_progress AS t
USING (
  SELECT n.* FROM (
  SELECT pseudonymize(r.learner_id) AS learner_pseudonym, r.lesson_id, r.course_id,
         r.percent_done, CAST(r.updated_at AS TIMESTAMP) AS updated_at,
         batch_first_at, batch_completed_at, is_deleted, lsn AS _source_lsn, source_ts AS _source_ts
  FROM (
    SELECT r, is_deleted, lsn, source_ts,
           min(CAST(r.updated_at AS TIMESTAMP)) OVER (PARTITION BY r.learner_id, r.lesson_id) AS batch_first_at,
           min(CASE WHEN r.percent_done >= 100 THEN CAST(r.updated_at AS TIMESTAMP) END)
             OVER (PARTITION BY r.learner_id, r.lesson_id) AS batch_completed_at,
           row_number() OVER (PARTITION BY r.learner_id, r.lesson_id ORDER BY lsn DESC, kafka_offset DESC) AS rn
    FROM (
      SELECT from_json(after, 'learner_id STRING, lesson_id STRING, course_id STRING, percent_done INT, updated_at STRING') AS r,
             op = 'd' OR get_json_object(after, '$.__deleted') = 'true' AS is_deleted,
             lsn, source_ts, kafka_offset
      FROM _src
    )
  ) WHERE rn = 1 AND r.learner_id IS NOT NULL AND r.lesson_id IS NOT NULL
  ) n
  -- only changes newer than silver: replayed / overlapping windows rewrite nothing
  LEFT JOIN silver.lesson_progress cur ON cur.learner_pseudonym = n.learner_pseudonym AND cur.lesson_id = n.lesson_id
  WHERE cur.learner_pseudonym IS NULL OR n._source_lsn > cur._source_lsn
) AS s
ON t.learner_pseudonym = s.learner_pseudonym AND t.lesson_id = s.lesson_id
WHEN MATCHED AND s._source_lsn > t._source_lsn THEN UPDATE SET
  course_id = s.course_id, percent_done = s.percent_done,
  first_progress_at = least(coalesce(t.first_progress_at, s.batch_first_at), s.batch_first_at),
  completed_at = coalesce(t.completed_at, s.batch_completed_at),
  updated_at = s.updated_at, is_deleted = s.is_deleted,
  _source_lsn = s._source_lsn, _source_ts = s._source_ts, _processed_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (learner_pseudonym, lesson_id, course_id, percent_done, first_progress_at, completed_at, updated_at,
   is_deleted, _source_lsn, _source_ts, _processed_at)
  VALUES (s.learner_pseudonym, s.lesson_id, s.course_id, s.percent_done, s.batch_first_at,
          s.batch_completed_at, s.updated_at, s.is_deleted, s._source_lsn, s._source_ts, current_timestamp());
