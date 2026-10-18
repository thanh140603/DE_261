-- silver.learners <- bronze.cdc_events (source_table = 'learners').
-- PII: learner_id is pseudonymised; email and full_name are dropped (PiiPolicy.drop_fields).
MERGE INTO silver.learners AS t
USING (
  SELECT n.* FROM (
  SELECT pseudonymize(r.learner_id) AS learner_pseudonym, r.organisation_id, r.advisor_id,
         r.country_code, CAST(r.signed_up_at AS TIMESTAMP) AS signed_up_at,
         CAST(r.updated_at AS TIMESTAMP) AS updated_at,
         is_deleted, lsn AS _source_lsn, source_ts AS _source_ts
  FROM (
    SELECT from_json(after, 'learner_id STRING, organisation_id STRING, advisor_id STRING, country_code STRING, signed_up_at STRING, updated_at STRING') AS r,
           op = 'd' OR get_json_object(after, '$.__deleted') = 'true' AS is_deleted,
           lsn, source_ts,
           row_number() OVER (PARTITION BY get_json_object(after, '$.learner_id')
                              ORDER BY lsn DESC, kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND r.learner_id IS NOT NULL
  ) n
  -- only changes newer than silver: replayed / overlapping windows rewrite nothing
  LEFT JOIN silver.learners cur ON cur.learner_pseudonym = n.learner_pseudonym
  WHERE cur.learner_pseudonym IS NULL OR n._source_lsn > cur._source_lsn
) AS s
ON t.learner_pseudonym = s.learner_pseudonym
WHEN MATCHED AND s._source_lsn > t._source_lsn THEN UPDATE SET
  organisation_id = s.organisation_id, advisor_id = s.advisor_id, country_code = s.country_code,
  signed_up_at = s.signed_up_at, updated_at = s.updated_at, is_deleted = s.is_deleted,
  _source_lsn = s._source_lsn, _source_ts = s._source_ts, _processed_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (learner_pseudonym, organisation_id, advisor_id, country_code, signed_up_at, updated_at,
   is_deleted, _source_lsn, _source_ts, _processed_at)
  VALUES (s.learner_pseudonym, s.organisation_id, s.advisor_id, s.country_code, s.signed_up_at,
          s.updated_at, s.is_deleted, s._source_lsn, s._source_ts, current_timestamp());
