-- silver.grades <- bronze.cdc_events (source_table = 'grades').
MERGE INTO silver.grades AS t
USING (
  SELECT n.* FROM (
  SELECT r.submission_id, r.score, r.pass_rate, CAST(r.graded_at AS TIMESTAMP) AS graded_at,
         is_deleted, lsn AS _source_lsn, source_ts AS _source_ts
  FROM (
    SELECT from_json(after, 'submission_id STRING, score DOUBLE, pass_rate DOUBLE, graded_at STRING') AS r,
           op = 'd' OR get_json_object(after, '$.__deleted') = 'true' AS is_deleted,
           lsn, source_ts,
           row_number() OVER (PARTITION BY get_json_object(after, '$.submission_id')
                              ORDER BY lsn DESC, kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND r.submission_id IS NOT NULL
  ) n
  -- only changes newer than silver: replayed / overlapping windows rewrite nothing
  LEFT JOIN silver.grades cur ON cur.submission_id = n.submission_id
  WHERE cur.submission_id IS NULL OR n._source_lsn > cur._source_lsn
) AS s
ON t.submission_id = s.submission_id
WHEN MATCHED AND s._source_lsn > t._source_lsn THEN UPDATE SET
  score = s.score, pass_rate = s.pass_rate, graded_at = s.graded_at, is_deleted = s.is_deleted,
  _source_lsn = s._source_lsn, _source_ts = s._source_ts, _processed_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (submission_id, score, pass_rate, graded_at, is_deleted, _source_lsn, _source_ts, _processed_at)
  VALUES (s.submission_id, s.score, s.pass_rate, s.graded_at, s.is_deleted, s._source_lsn, s._source_ts, current_timestamp());
