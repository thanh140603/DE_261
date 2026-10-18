-- silver.submissions <- bronze.cdc_events (source_table = 'submissions').
MERGE INTO silver.submissions AS t
USING (
  SELECT n.* FROM (
  SELECT r.submission_id, pseudonymize(r.learner_id) AS learner_pseudonym, r.assignment_id,
         r.attempt_number, r.language, r.status, r.code_ref,
         CAST(r.submitted_at AS TIMESTAMP) AS submitted_at, CAST(r.updated_at AS TIMESTAMP) AS updated_at,
         is_deleted, lsn AS _source_lsn, source_ts AS _source_ts
  FROM (
    SELECT from_json(after, 'submission_id STRING, learner_id STRING, assignment_id STRING, attempt_number INT, language STRING, code_ref STRING, status STRING, submitted_at STRING, updated_at STRING') AS r,
           op = 'd' OR get_json_object(after, '$.__deleted') = 'true' AS is_deleted,
           lsn, source_ts,
           row_number() OVER (PARTITION BY get_json_object(after, '$.submission_id')
                              ORDER BY lsn DESC, kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND r.submission_id IS NOT NULL
  ) n
  -- only changes newer than silver: replayed / overlapping windows rewrite nothing
  LEFT JOIN silver.submissions cur ON cur.submission_id = n.submission_id
  WHERE cur.submission_id IS NULL OR n._source_lsn > cur._source_lsn
) AS s
ON t.submission_id = s.submission_id
WHEN MATCHED AND s._source_lsn > t._source_lsn THEN UPDATE SET
  learner_pseudonym = s.learner_pseudonym, assignment_id = s.assignment_id,
  attempt_number = s.attempt_number, language = s.language, status = s.status, code_ref = s.code_ref,
  submitted_at = s.submitted_at, updated_at = s.updated_at, is_deleted = s.is_deleted,
  _source_lsn = s._source_lsn, _source_ts = s._source_ts, _processed_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (submission_id, learner_pseudonym, assignment_id, attempt_number, language, status, code_ref,
   submitted_at, updated_at, is_deleted, _source_lsn, _source_ts, _processed_at)
  VALUES (s.submission_id, s.learner_pseudonym, s.assignment_id, s.attempt_number, s.language, s.status,
          s.code_ref, s.submitted_at, s.updated_at, s.is_deleted, s._source_lsn, s._source_ts, current_timestamp());
