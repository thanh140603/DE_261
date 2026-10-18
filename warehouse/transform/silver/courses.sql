-- silver.courses <- bronze.cdc_events (source_table = 'courses').
MERGE INTO silver.courses AS t
USING (
  SELECT n.* FROM (
  SELECT r.course_id, r.title, r.skill, r.level, r.owner_organisation_id,
         CAST(r.updated_at AS TIMESTAMP) AS updated_at,
         is_deleted, lsn AS _source_lsn, source_ts AS _source_ts
  FROM (
    SELECT from_json(after, 'course_id STRING, title STRING, skill STRING, level STRING, owner_organisation_id STRING, updated_at STRING') AS r,
           op = 'd' OR get_json_object(after, '$.__deleted') = 'true' AS is_deleted,
           lsn, source_ts,
           row_number() OVER (PARTITION BY get_json_object(after, '$.course_id')
                              ORDER BY lsn DESC, kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND r.course_id IS NOT NULL
  ) n
  -- only changes newer than silver: replayed / overlapping windows rewrite nothing
  LEFT JOIN silver.courses cur ON cur.course_id = n.course_id
  WHERE cur.course_id IS NULL OR n._source_lsn > cur._source_lsn
) AS s
ON t.course_id = s.course_id
WHEN MATCHED AND s._source_lsn > t._source_lsn THEN UPDATE SET
  title = s.title, skill = s.skill, level = s.level, owner_organisation_id = s.owner_organisation_id,
  updated_at = s.updated_at, is_deleted = s.is_deleted,
  _source_lsn = s._source_lsn, _source_ts = s._source_ts, _processed_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (course_id, title, skill, level, owner_organisation_id, updated_at, is_deleted, _source_lsn, _source_ts, _processed_at)
  VALUES (s.course_id, s.title, s.skill, s.level, s.owner_organisation_id, s.updated_at, s.is_deleted,
          s._source_lsn, s._source_ts, current_timestamp());
