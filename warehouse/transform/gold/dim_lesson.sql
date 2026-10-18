-- gold.dim_lesson (SCD1, full rebuild).
INSERT OVERWRITE gold.dim_lesson
WITH src AS (SELECT lesson_id, course_id, title, ordinal, content_id FROM silver.lessons),
refs AS (
  SELECT lesson_id FROM silver.lesson_progress
  UNION SELECT lesson_id FROM silver.assignments WHERE lesson_id IS NOT NULL
  UNION SELECT lesson_id FROM gold.dim_lesson WHERE is_inferred
)
SELECT xxhash64(lesson_id), lesson_id, course_id,
       CASE WHEN course_id IS NULL THEN -1 ELSE xxhash64(course_id) END,
       title, ordinal, content_id, false, current_timestamp()
FROM src
UNION ALL
SELECT xxhash64(r.lesson_id), r.lesson_id, NULL, -1, NULL, NULL, NULL, true, current_timestamp()
FROM refs r LEFT ANTI JOIN src s ON s.lesson_id = r.lesson_id
UNION ALL
SELECT -1, 'n/a', NULL, -1, 'Unknown lesson', NULL, NULL, false, current_timestamp();
