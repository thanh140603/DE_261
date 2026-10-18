-- gold.dim_test_case (SCD1, full rebuild). Natural key (assignment_id, test_case_id): test case
-- ids are only unique inside an assignment.
INSERT OVERWRITE gold.dim_test_case
WITH src AS (SELECT assignment_id, test_case_id, name, weight, is_hidden FROM silver.test_cases),
refs AS (
  SELECT DISTINCT s.assignment_id, r.test_case_id
  FROM silver.test_case_results r
  JOIN silver.submissions s ON s.submission_id = r.submission_id
  UNION SELECT assignment_id, test_case_id FROM gold.dim_test_case WHERE is_inferred
)
SELECT xxhash64(assignment_id, test_case_id), assignment_id, test_case_id, xxhash64(assignment_id),
       name, weight, is_hidden, false, current_timestamp()
FROM src
UNION ALL
SELECT xxhash64(r.assignment_id, r.test_case_id), r.assignment_id, r.test_case_id,
       xxhash64(r.assignment_id), NULL, NULL, NULL, true, current_timestamp()
FROM refs r LEFT ANTI JOIN src s
  ON s.assignment_id = r.assignment_id AND s.test_case_id = r.test_case_id;
