-- gold.fct_submission (window on submitted_date). OLTP submission + grade (CDC) enriched with
-- the latest sandbox run (a re-run supersedes earlier runs of the same submission).
INSERT INTO gold.fct_submission
REPLACE WHERE submitted_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
WITH latest_run AS (
  SELECT * FROM (
    SELECT *, row_number() OVER (PARTITION BY submission_id ORDER BY executed_at DESC, worker_run_id DESC) AS rn
    FROM silver.submission_executions
  ) WHERE rn = 1
)
SELECT s.submission_id, CAST(s.submitted_at AS DATE) AS submitted_date,
       CAST(date_format(s.submitted_at, 'yyyyMMdd') AS INT) AS date_key,
       coalesce(l.learner_key, -1), xxhash64(s.assignment_id),
       CASE WHEN a.course_id IS NULL THEN -1 ELSE xxhash64(a.course_id) END,
       s.learner_pseudonym, s.assignment_id, a.course_id, s.attempt_number, s.attempt_number = 1,
       s.language, s.status, g.score,
       coalesce(g.pass_rate, CASE WHEN r.tests_total > 0 THEN r.tests_passed / r.tests_total END) AS pass_rate,
       coalesce(g.pass_rate, CASE WHEN r.tests_total > 0 THEN r.tests_passed / r.tests_total END) >= 1.0 AS is_passed,
       r.tests_total, r.tests_passed, r.exec_time_ms, r.max_rss_kb, r.exit_code, r.timed_out, r.has_stderr,
       s.submitted_at, g.graded_at,
       CAST(g.graded_at AS DOUBLE) - CAST(s.submitted_at AS DOUBLE) AS seconds_to_grade,
       current_timestamp()
FROM silver.submissions s
LEFT JOIN silver.grades g ON g.submission_id = s.submission_id AND NOT g.is_deleted
LEFT JOIN latest_run r ON r.submission_id = s.submission_id
LEFT JOIN silver.assignments a ON a.assignment_id = s.assignment_id
LEFT JOIN gold.dim_learner l
  ON l.learner_pseudonym = s.learner_pseudonym
 AND s.submitted_at >= l.valid_from AND s.submitted_at < l.valid_to
WHERE NOT s.is_deleted
  AND CAST(s.submitted_at AS DATE) BETWEEN DATE'${window_start}' AND DATE'${window_end}';
