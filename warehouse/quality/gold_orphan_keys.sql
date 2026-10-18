-- Referential integrity of facts in the processed window: every surrogate key must exist in
-- its dimension (hashed SCD1 keys are computed, so this is where a mismatch would surface).
SELECT sum(n) AS violations FROM (
  SELECT count(*) AS n FROM gold.fct_learning_event f
    LEFT ANTI JOIN gold.dim_course d ON d.course_key = f.course_key
    WHERE f.event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
  UNION ALL SELECT count(*) FROM gold.fct_learning_event f
    LEFT ANTI JOIN gold.dim_learner d ON d.learner_key = f.learner_key
    WHERE f.event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
  UNION ALL SELECT count(*) FROM gold.fct_learning_event f
    LEFT ANTI JOIN gold.dim_content d ON d.content_key = f.content_key
    WHERE f.event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
  UNION ALL SELECT count(*) FROM gold.fct_test_case_result f
    LEFT ANTI JOIN gold.dim_test_case d ON d.test_case_key = f.test_case_key
    WHERE f.submitted_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
  UNION ALL SELECT count(*) FROM gold.fct_submission f
    LEFT ANTI JOIN gold.dim_assignment d ON d.assignment_key = f.assignment_key
    WHERE f.submitted_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
  UNION ALL SELECT count(*) FROM gold.fct_enrollment f
    LEFT ANTI JOIN gold.dim_organisation d ON d.organisation_key = f.organisation_key
);
