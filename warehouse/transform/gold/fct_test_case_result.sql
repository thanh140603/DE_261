-- gold.fct_test_case_result (window on submitted_date). Assertions of the latest sandbox run.
INSERT INTO gold.fct_test_case_result
REPLACE WHERE submitted_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
WITH latest_run AS (
  SELECT submission_id, worker_run_id FROM (
    SELECT submission_id, worker_run_id,
           row_number() OVER (PARTITION BY submission_id ORDER BY executed_at DESC, worker_run_id DESC) AS rn
    FROM silver.submission_executions
  ) WHERE rn = 1
)
SELECT t.submission_id, CAST(s.submitted_at AS DATE),
       CAST(date_format(s.submitted_at, 'yyyyMMdd') AS INT),
       xxhash64(s.assignment_id, t.test_case_id), xxhash64(s.assignment_id),
       coalesce(l.learner_key, -1), s.assignment_id, t.test_case_id, s.learner_pseudonym,
       s.attempt_number, t.status, t.status = 'passed', t.duration_ms, t.executed_at,
       current_timestamp()
FROM silver.test_case_results t
JOIN latest_run lr ON lr.submission_id = t.submission_id AND lr.worker_run_id = t.worker_run_id
JOIN silver.submissions s ON s.submission_id = t.submission_id AND NOT s.is_deleted
LEFT JOIN gold.dim_learner l
  ON l.learner_pseudonym = s.learner_pseudonym
 AND s.submitted_at >= l.valid_from AND s.submitted_at < l.valid_to
WHERE CAST(s.submitted_at AS DATE) BETWEEN DATE'${window_start}' AND DATE'${window_end}';
