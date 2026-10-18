-- gold.dim_learner (SCD2, incremental). Tracked attributes: organisation_id, advisor_id,
-- country_code. Staged-MERGE pattern: every silver learner appears once keyed by pseudonym
-- (matches its current row) and, when its attributes changed, a second time with a NULL key
-- (never matches -> inserted as the new version). Effective date = OLTP updated_at.
MERGE INTO gold.dim_learner AS t
USING (
  WITH src AS (
    SELECT s.learner_pseudonym, s.organisation_id, s.advisor_id, s.country_code,
           CAST(s.signed_up_at AS DATE) AS signed_up_date,
           xxhash64(concat_ws('|', coalesce(s.organisation_id, '~'), coalesce(s.advisor_id, '~'),
                              coalesce(s.country_code, '~'))) AS attr_hash,
           greatest(coalesce(s.updated_at, current_timestamp()),
                    coalesce(d.valid_from + INTERVAL 1 SECOND, TIMESTAMP'1900-01-01 00:00:00')) AS effective_from,
           d.learner_pseudonym IS NOT NULL AND NOT d.is_inferred AND d.attr_hash <> xxhash64(concat_ws('|',
             coalesce(s.organisation_id, '~'), coalesce(s.advisor_id, '~'), coalesce(s.country_code, '~'))) AS changed
    FROM silver.learners s
    LEFT JOIN gold.dim_learner d ON d.learner_pseudonym = s.learner_pseudonym AND d.is_current
  )
  SELECT learner_pseudonym AS merge_key, * FROM src
  UNION ALL
  SELECT CAST(NULL AS STRING) AS merge_key, * FROM src WHERE changed
) AS s
ON t.learner_pseudonym = s.merge_key AND t.is_current
WHEN MATCHED AND t.is_inferred THEN UPDATE SET
  organisation_id = s.organisation_id, advisor_id = s.advisor_id, country_code = s.country_code,
  signed_up_date = s.signed_up_date, attr_hash = s.attr_hash, is_inferred = false,
  _built_at = current_timestamp()
WHEN MATCHED AND s.changed THEN UPDATE SET
  valid_to = s.effective_from, is_current = false, _built_at = current_timestamp()
WHEN MATCHED AND t.signed_up_date IS DISTINCT FROM s.signed_up_date THEN UPDATE SET
  signed_up_date = s.signed_up_date, _built_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (learner_key, learner_pseudonym, organisation_id, advisor_id, country_code, signed_up_date,
   attr_hash, valid_from, valid_to, is_current, is_inferred, _built_at)
  VALUES (
    xxhash64(s.learner_pseudonym, CASE WHEN s.merge_key IS NULL THEN s.effective_from
                                       ELSE TIMESTAMP'1900-01-01 00:00:00' END),
    s.learner_pseudonym, s.organisation_id, s.advisor_id, s.country_code, s.signed_up_date,
    s.attr_hash,
    CASE WHEN s.merge_key IS NULL THEN s.effective_from ELSE TIMESTAMP'1900-01-01 00:00:00' END,
    TIMESTAMP'9999-12-31 00:00:00', true, false, current_timestamp());

-- Inferred members: pseudonyms referenced by silver facts but not yet in silver.learners.
INSERT INTO gold.dim_learner
SELECT xxhash64(r.learner_pseudonym, TIMESTAMP'1900-01-01 00:00:00'), r.learner_pseudonym,
       NULL, NULL, NULL, NULL, CAST(NULL AS BIGINT), TIMESTAMP'1900-01-01 00:00:00',
       TIMESTAMP'9999-12-31 00:00:00', true, true, current_timestamp()
FROM (
  SELECT learner_pseudonym FROM silver.enrollments
  UNION SELECT learner_pseudonym FROM silver.submissions
  UNION SELECT learner_pseudonym FROM silver.lesson_progress
  UNION SELECT learner_pseudonym FROM silver.risk_scores
  UNION SELECT learner_pseudonym FROM silver.dropout_alerts
  UNION SELECT learner_pseudonym FROM silver.learning_events
        WHERE event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
) r
LEFT ANTI JOIN gold.dim_learner d ON d.learner_pseudonym = r.learner_pseudonym;

-- Unknown member (-1), created once.
INSERT INTO gold.dim_learner
SELECT -1, 'n/a', NULL, NULL, NULL, NULL, CAST(NULL AS BIGINT), TIMESTAMP'1900-01-01 00:00:00',
       TIMESTAMP'9999-12-31 00:00:00', true, false, current_timestamp()
WHERE NOT EXISTS (SELECT 1 FROM gold.dim_learner WHERE learner_key = -1);
