-- silver.assignments <- bronze.cdc_events (source_table = 'assignments').
MERGE INTO silver.assignments AS t
USING (
  SELECT n.* FROM (
  SELECT r.assignment_id, r.course_id, r.lesson_id, r.title, r.language,
         CAST(r.due_at AS TIMESTAMP) AS due_at, r.max_score, CAST(r.updated_at AS TIMESTAMP) AS updated_at,
         is_deleted, lsn AS _source_lsn, source_ts AS _source_ts
  FROM (
    SELECT from_json(after, 'assignment_id STRING, course_id STRING, lesson_id STRING, title STRING, language STRING, due_at STRING, max_score DOUBLE, updated_at STRING') AS r,
           op = 'd' OR get_json_object(after, '$.__deleted') = 'true' AS is_deleted,
           lsn, source_ts,
           row_number() OVER (PARTITION BY get_json_object(after, '$.assignment_id')
                              ORDER BY lsn DESC, kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND r.assignment_id IS NOT NULL
  ) n
  -- only changes newer than silver: replayed / overlapping windows rewrite nothing
  LEFT JOIN silver.assignments cur ON cur.assignment_id = n.assignment_id
  WHERE cur.assignment_id IS NULL OR n._source_lsn > cur._source_lsn
) AS s
ON t.assignment_id = s.assignment_id
WHEN MATCHED AND s._source_lsn > t._source_lsn THEN UPDATE SET
  course_id = s.course_id, lesson_id = s.lesson_id, title = s.title, language = s.language,
  due_at = s.due_at, max_score = s.max_score, updated_at = s.updated_at, is_deleted = s.is_deleted,
  _source_lsn = s._source_lsn, _source_ts = s._source_ts, _processed_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (assignment_id, course_id, lesson_id, title, language, due_at, max_score, updated_at, is_deleted,
   _source_lsn, _source_ts, _processed_at)
  VALUES (s.assignment_id, s.course_id, s.lesson_id, s.title, s.language, s.due_at, s.max_score,
          s.updated_at, s.is_deleted, s._source_lsn, s._source_ts, current_timestamp());
