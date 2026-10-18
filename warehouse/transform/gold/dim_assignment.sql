-- gold.dim_assignment (SCD1, full rebuild) with test_case_count.
INSERT OVERWRITE gold.dim_assignment
WITH src AS (
  SELECT a.assignment_id, a.course_id, a.lesson_id, a.title, a.language, a.due_at, a.max_score,
         coalesce(t.n, 0) AS test_case_count
  FROM silver.assignments a
  LEFT JOIN (SELECT assignment_id, CAST(count(*) AS INT) AS n
             FROM silver.test_cases WHERE NOT is_deleted GROUP BY assignment_id) t
    ON t.assignment_id = a.assignment_id
),
refs AS (
  SELECT assignment_id FROM silver.submissions
  UNION SELECT assignment_id FROM silver.test_cases
  UNION SELECT assignment_id FROM gold.dim_assignment WHERE is_inferred
)
SELECT xxhash64(assignment_id), assignment_id, course_id,
       CASE WHEN course_id IS NULL THEN -1 ELSE xxhash64(course_id) END,
       lesson_id, title, language, due_at, max_score, test_case_count, false, current_timestamp()
FROM src
UNION ALL
SELECT xxhash64(r.assignment_id), r.assignment_id, NULL, -1, NULL, NULL, NULL, NULL, NULL, 0, true,
       current_timestamp()
FROM refs r LEFT ANTI JOIN src s ON s.assignment_id = r.assignment_id
UNION ALL
SELECT -1, 'n/a', NULL, -1, NULL, 'Unknown assignment', NULL, NULL, NULL, 0, false, current_timestamp();
