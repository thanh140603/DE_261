-- gold.fct_enrollment (full rebuild; accumulating snapshot). Milestones come from silver
-- (captured while applying CDC) and from gold activity/progress facts built earlier in the run.
INSERT OVERWRITE gold.fct_enrollment
WITH activity AS (
  SELECT learner_pseudonym, course_id, min(first_event_at) AS first_at, max(last_event_at) AS last_at
  FROM gold.fct_learner_daily_activity GROUP BY learner_pseudonym, course_id
),
progress AS (
  SELECT learner_pseudonym, course_id, CAST(count_if(is_completed) AS INT) AS lessons_completed
  FROM gold.fct_lesson_progress GROUP BY learner_pseudonym, course_id
),
grading AS (
  SELECT learner_pseudonym, course_id, count(*) AS submissions, avg(pass_rate) AS avg_pass_rate
  FROM gold.fct_submission GROUP BY learner_pseudonym, course_id
)
SELECT e.enrollment_id, coalesce(l.learner_key, -1), xxhash64(e.course_id),
       CASE WHEN e.organisation_id IS NULL THEN -1 ELSE xxhash64(e.organisation_id) END,
       e.learner_pseudonym, e.course_id, e.organisation_id, e.status,
       CAST(date_format(e.enrolled_at, 'yyyyMMdd') AS INT),
       CAST(date_format(a.first_at, 'yyyyMMdd') AS INT),
       CAST(date_format(a.last_at, 'yyyyMMdd') AS INT),
       CAST(date_format(e.completed_at, 'yyyyMMdd') AS INT),
       CAST(date_format(e.dropped_at, 'yyyyMMdd') AS INT),
       e.enrolled_at, a.first_at, a.last_at, e.completed_at, e.dropped_at,
       coalesce(c.lesson_count, 0) AS lessons_total,
       least(coalesce(p.lessons_completed, 0), coalesce(c.lesson_count, 0)) AS lessons_completed,
       CASE WHEN coalesce(c.lesson_count, 0) = 0 THEN 0.0
            ELSE round(least(coalesce(p.lessons_completed, 0), c.lesson_count) / c.lesson_count, 4) END,
       coalesce(g.submissions, 0), g.avg_pass_rate,
       datediff(e.completed_at, e.enrolled_at), current_timestamp()
FROM silver.enrollments e
LEFT JOIN gold.dim_course c ON c.course_id = e.course_id
LEFT JOIN activity a ON a.learner_pseudonym = e.learner_pseudonym AND a.course_id = e.course_id
LEFT JOIN progress p ON p.learner_pseudonym = e.learner_pseudonym AND p.course_id = e.course_id
LEFT JOIN grading g ON g.learner_pseudonym = e.learner_pseudonym AND g.course_id = e.course_id
LEFT JOIN gold.dim_learner l
  ON l.learner_pseudonym = e.learner_pseudonym
 AND coalesce(e.enrolled_at, current_timestamp()) >= l.valid_from
 AND coalesce(e.enrolled_at, current_timestamp()) < l.valid_to
WHERE NOT e.is_deleted;
