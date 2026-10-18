-- gold.dim_course (SCD1, full rebuild) with lesson_count, the completion-rate denominator.
-- Inferred members: course ids referenced by silver facts (recent telemetry window included)
-- plus inferred rows already in the dimension, so an inferred key never disappears.
INSERT OVERWRITE gold.dim_course
WITH src AS (
  SELECT c.course_id, c.title, c.skill, c.level, c.owner_organisation_id,
         coalesce(l.lesson_count, 0) AS lesson_count
  FROM silver.courses c
  LEFT JOIN (SELECT course_id, CAST(count(*) AS INT) AS lesson_count
             FROM silver.lessons WHERE NOT is_deleted GROUP BY course_id) l
    ON l.course_id = c.course_id
),
refs AS (
  SELECT course_id FROM silver.enrollments
  UNION SELECT course_id FROM silver.lessons WHERE course_id IS NOT NULL
  UNION SELECT course_id FROM silver.assignments WHERE course_id IS NOT NULL
  UNION SELECT course_id FROM silver.content_versions WHERE course_id IS NOT NULL
  UNION SELECT course_id FROM silver.risk_scores
  UNION SELECT course_id FROM silver.learning_events
        WHERE event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
  UNION SELECT course_id FROM gold.dim_course WHERE is_inferred
)
SELECT xxhash64(course_id), course_id, title, skill, level, owner_organisation_id, lesson_count,
       false, current_timestamp()
FROM src
UNION ALL
SELECT xxhash64(r.course_id), r.course_id, NULL, NULL, NULL, NULL, 0, true, current_timestamp()
FROM refs r LEFT ANTI JOIN src s ON s.course_id = r.course_id
UNION ALL
SELECT -1, 'n/a', 'Unknown course', NULL, NULL, NULL, 0, false, current_timestamp();
