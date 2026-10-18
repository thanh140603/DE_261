-- silver.content_versions <- bronze.cdc_events (source_table = 'course_content').
-- Keyed by (content_id, version), not content_id: every published version is kept so the
-- SCD2 dim_content and per-version heatmaps (BR7) have the full history. published_at is the
-- first time a version was seen and never moves.
MERGE INTO silver.content_versions AS t
USING (
  SELECT n.* FROM (
  SELECT r.content_id, r.version, r.course_id, r.content_type, r.title, r.object_key, r.duration_sec,
         published_at, CAST(r.updated_at AS TIMESTAMP) AS last_changed_at,
         is_deleted, lsn AS _source_lsn
  FROM (
    SELECT from_json(after, 'content_id STRING, course_id STRING, content_type STRING, title STRING, version INT, object_key STRING, duration_sec INT, updated_at STRING') AS r,
           op = 'd' OR get_json_object(after, '$.__deleted') = 'true' AS is_deleted,
           lsn,
           min(CAST(get_json_object(after, '$.updated_at') AS TIMESTAMP)) OVER (
             PARTITION BY get_json_object(after, '$.content_id'), get_json_object(after, '$.version')) AS published_at,
           row_number() OVER (PARTITION BY get_json_object(after, '$.content_id'), get_json_object(after, '$.version')
                              ORDER BY lsn DESC, kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND r.content_id IS NOT NULL AND r.version IS NOT NULL
  ) n
  -- only changes newer than silver: replayed / overlapping windows rewrite nothing
  LEFT JOIN silver.content_versions cur ON cur.content_id = n.content_id AND cur.version = n.version
  WHERE cur.content_id IS NULL OR n._source_lsn > cur._source_lsn
) AS s
ON t.content_id = s.content_id AND t.version = s.version
WHEN MATCHED AND s._source_lsn > t._source_lsn THEN UPDATE SET
  course_id = s.course_id, content_type = s.content_type, title = s.title, object_key = s.object_key,
  duration_sec = s.duration_sec, published_at = least(t.published_at, s.published_at),
  last_changed_at = s.last_changed_at, is_deleted = s.is_deleted,
  _source_lsn = s._source_lsn, _processed_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (content_id, version, course_id, content_type, title, object_key, duration_sec, published_at,
   last_changed_at, is_deleted, _source_lsn, _processed_at)
  VALUES (s.content_id, s.version, s.course_id, s.content_type, s.title, s.object_key, s.duration_sec,
          s.published_at, s.last_changed_at, s.is_deleted, s._source_lsn, current_timestamp());
