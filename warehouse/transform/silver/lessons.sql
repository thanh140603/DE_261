-- silver.lessons <- bronze.cdc_events (source_table = 'lessons').
MERGE INTO silver.lessons AS t
USING (
  SELECT n.* FROM (
  SELECT r.lesson_id, r.course_id, r.content_id, r.title, r.ordinal,
         CAST(r.updated_at AS TIMESTAMP) AS updated_at,
         is_deleted, lsn AS _source_lsn, source_ts AS _source_ts
  FROM (
    SELECT from_json(after, 'lesson_id STRING, course_id STRING, content_id STRING, title STRING, ordinal INT, updated_at STRING') AS r,
           op = 'd' OR get_json_object(after, '$.__deleted') = 'true' AS is_deleted,
           lsn, source_ts,
           row_number() OVER (PARTITION BY get_json_object(after, '$.lesson_id')
                              ORDER BY lsn DESC, kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND r.lesson_id IS NOT NULL
  ) n
  -- only changes newer than silver: replayed / overlapping windows rewrite nothing
  LEFT JOIN silver.lessons cur ON cur.lesson_id = n.lesson_id
  WHERE cur.lesson_id IS NULL OR n._source_lsn > cur._source_lsn
) AS s
ON t.lesson_id = s.lesson_id
WHEN MATCHED AND s._source_lsn > t._source_lsn THEN UPDATE SET
  course_id = s.course_id, content_id = s.content_id, title = s.title, ordinal = s.ordinal,
  updated_at = s.updated_at, is_deleted = s.is_deleted,
  _source_lsn = s._source_lsn, _source_ts = s._source_ts, _processed_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (lesson_id, course_id, content_id, title, ordinal, updated_at, is_deleted, _source_lsn, _source_ts, _processed_at)
  VALUES (s.lesson_id, s.course_id, s.content_id, s.title, s.ordinal, s.updated_at, s.is_deleted,
          s._source_lsn, s._source_ts, current_timestamp());
