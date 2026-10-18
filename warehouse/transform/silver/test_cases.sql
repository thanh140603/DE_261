-- silver.test_cases <- bronze.cdc_events (source_table = 'test_cases'). Key: (assignment_id, test_case_id).
MERGE INTO silver.test_cases AS t
USING (
  SELECT n.* FROM (
  SELECT r.assignment_id, r.test_case_id, r.name, r.weight, r.is_hidden,
         CAST(r.updated_at AS TIMESTAMP) AS updated_at,
         is_deleted, lsn AS _source_lsn, source_ts AS _source_ts
  FROM (
    SELECT from_json(after, 'assignment_id STRING, test_case_id STRING, name STRING, weight DOUBLE, is_hidden BOOLEAN, updated_at STRING') AS r,
           op = 'd' OR get_json_object(after, '$.__deleted') = 'true' AS is_deleted,
           lsn, source_ts,
           row_number() OVER (PARTITION BY get_json_object(after, '$.assignment_id'), get_json_object(after, '$.test_case_id')
                              ORDER BY lsn DESC, kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND r.assignment_id IS NOT NULL AND r.test_case_id IS NOT NULL
  ) n
  -- only changes newer than silver: replayed / overlapping windows rewrite nothing
  LEFT JOIN silver.test_cases cur ON cur.assignment_id = n.assignment_id AND cur.test_case_id = n.test_case_id
  WHERE cur.assignment_id IS NULL OR n._source_lsn > cur._source_lsn
) AS s
ON t.assignment_id = s.assignment_id AND t.test_case_id = s.test_case_id
WHEN MATCHED AND s._source_lsn > t._source_lsn THEN UPDATE SET
  name = s.name, weight = s.weight, is_hidden = s.is_hidden, updated_at = s.updated_at,
  is_deleted = s.is_deleted, _source_lsn = s._source_lsn, _source_ts = s._source_ts,
  _processed_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (assignment_id, test_case_id, name, weight, is_hidden, updated_at, is_deleted, _source_lsn, _source_ts, _processed_at)
  VALUES (s.assignment_id, s.test_case_id, s.name, s.weight, s.is_hidden, s.updated_at, s.is_deleted,
          s._source_lsn, s._source_ts, current_timestamp());
