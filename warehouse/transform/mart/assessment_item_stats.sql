-- mart.assessment_item_stats (BR4, snapshot partition as_of_date = run_date).
-- BuildAssessmentMart semantics: per (assignment, test case) over the trailing window,
-- pass_rate = passes / attempts; anomalous when attempts >= min_attempts AND
-- pass_rate <= max_pass_rate AND (assignment median - pass_rate) >= min_delta.
INSERT INTO mart.assessment_item_stats
REPLACE WHERE as_of_date = DATE'${run_date}'
WITH items AS (
  SELECT assignment_id, test_case_id, count(*) AS attempts, count_if(is_passed) AS passes
  FROM gold.fct_test_case_result
  WHERE submitted_date BETWEEN date_sub(DATE'${run_date}', ${assessment_window_days} - 1) AND DATE'${run_date}'
  GROUP BY assignment_id, test_case_id
),
rated AS (
  SELECT *, passes / attempts AS pass_rate,
         percentile(passes / attempts, 0.5) OVER (PARTITION BY assignment_id) AS median_rate
  FROM items
)
SELECT DATE'${run_date}', date_sub(DATE'${run_date}', ${assessment_window_days} - 1), DATE'${run_date}',
       a.course_id, r.assignment_id, a.assignment_title, r.test_case_id, t.test_case_name,
       r.attempts, r.passes, round(r.pass_rate, 3), round(r.median_rate, 3),
       r.attempts >= ${anomaly_min_attempts}
         AND r.pass_rate <= ${anomaly_max_pass_rate}
         AND (r.median_rate - r.pass_rate) >= ${anomaly_min_delta} AS is_anomalous,
       ${anomaly_min_attempts}, ${anomaly_max_pass_rate}, ${anomaly_min_delta}, current_timestamp()
FROM rated r
LEFT JOIN gold.dim_assignment a ON a.assignment_id = r.assignment_id
LEFT JOIN gold.dim_test_case t ON t.assignment_id = r.assignment_id AND t.test_case_id = r.test_case_id;
