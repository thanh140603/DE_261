-- silver.enrollments <- bronze.cdc_events (source_table = 'enrollments').
-- Captures accumulating-snapshot milestones while applying CDC: completed_at / dropped_at are
-- the first time each status was observed and are never overwritten afterwards.
MERGE INTO silver.enrollments AS t
USING (
  SELECT n.* FROM (
  SELECT r.enrollment_id, pseudonymize(r.learner_id) AS learner_pseudonym, r.course_id,
         r.organisation_id, r.status, CAST(r.enrolled_at AS TIMESTAMP) AS enrolled_at,
         CAST(r.updated_at AS TIMESTAMP) AS updated_at, batch_completed_at, batch_dropped_at,
         is_deleted, lsn AS _source_lsn, source_ts AS _source_ts
  FROM (
    SELECT r, is_deleted, lsn, source_ts, kafka_offset,
           min(CASE WHEN r.status = 'completed' THEN CAST(r.updated_at AS TIMESTAMP) END)
             OVER (PARTITION BY r.enrollment_id) AS batch_completed_at,
           min(CASE WHEN r.status = 'dropped' THEN CAST(r.updated_at AS TIMESTAMP) END)
             OVER (PARTITION BY r.enrollment_id) AS batch_dropped_at,
           row_number() OVER (PARTITION BY r.enrollment_id ORDER BY lsn DESC, kafka_offset DESC) AS rn
    FROM (
      SELECT from_json(after, 'enrollment_id STRING, learner_id STRING, course_id STRING, organisation_id STRING, status STRING, enrolled_at STRING, updated_at STRING') AS r,
             op = 'd' OR get_json_object(after, '$.__deleted') = 'true' AS is_deleted,
             lsn, source_ts, kafka_offset
      FROM _src
    )
  ) WHERE rn = 1 AND r.enrollment_id IS NOT NULL
  ) n
  -- only changes newer than silver: replayed / overlapping windows rewrite nothing
  LEFT JOIN silver.enrollments cur ON cur.enrollment_id = n.enrollment_id
  WHERE cur.enrollment_id IS NULL OR n._source_lsn > cur._source_lsn
) AS s
ON t.enrollment_id = s.enrollment_id
WHEN MATCHED AND s._source_lsn > t._source_lsn THEN UPDATE SET
  learner_pseudonym = s.learner_pseudonym, course_id = s.course_id, organisation_id = s.organisation_id,
  status = s.status, enrolled_at = s.enrolled_at,
  completed_at = coalesce(t.completed_at, s.batch_completed_at),
  dropped_at = coalesce(t.dropped_at, s.batch_dropped_at),
  updated_at = s.updated_at, is_deleted = s.is_deleted,
  _source_lsn = s._source_lsn, _source_ts = s._source_ts, _processed_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (enrollment_id, learner_pseudonym, course_id, organisation_id, status, enrolled_at, completed_at,
   dropped_at, updated_at, is_deleted, _source_lsn, _source_ts, _processed_at)
  VALUES (s.enrollment_id, s.learner_pseudonym, s.course_id, s.organisation_id, s.status, s.enrolled_at,
          s.batch_completed_at, s.batch_dropped_at, s.updated_at, s.is_deleted, s._source_lsn,
          s._source_ts, current_timestamp());
