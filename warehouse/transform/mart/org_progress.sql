-- mart.org_progress (BR6, snapshot partition as_of_date = run_date).
-- BuildOrgProgressReport semantics with MinCohortPolicy: an organisation x course cell with
-- fewer than k enrolled learners is published with its size only - every rate is NULL.
-- completion_rate = mean over the cohort of lessons_completed / lessons_total;
-- avg_mastery     = mean over the cohort of the learner's average pass rate in that course
--                   (0 when the learner has no graded submission, as in the use case).
INSERT INTO mart.org_progress
REPLACE WHERE as_of_date = DATE'${run_date}'
WITH cohort AS (
  SELECT f.organisation_id, f.course_id,
         count(DISTINCT f.learner_pseudonym)                  AS cohort_size,
         avg(f.progress_ratio)                                AS completion_rate,
         avg(coalesce(f.avg_pass_rate, 0.0))                  AS avg_mastery,
         count(DISTINCT CASE WHEN f.status = 'completed' OR f.progress_ratio >= 1.0
                             THEN f.learner_pseudonym END)    AS completed_learners
  FROM gold.fct_enrollment f
  WHERE f.organisation_id IS NOT NULL
  GROUP BY f.organisation_id, f.course_id
)
SELECT DATE'${run_date}', c.organisation_id, o.organisation_name, c.course_id, d.course_title, d.skill,
       c.cohort_size,
       CASE WHEN c.cohort_size >= ${min_cohort_k} THEN round(c.completion_rate, 3) END,
       CASE WHEN c.cohort_size >= ${min_cohort_k} THEN round(c.avg_mastery, 3) END,
       CASE WHEN c.cohort_size >= ${min_cohort_k} THEN c.completed_learners END,
       c.cohort_size < ${min_cohort_k}, ${min_cohort_k}, current_timestamp()
FROM cohort c
LEFT JOIN gold.dim_organisation o ON o.organisation_id = c.organisation_id
LEFT JOIN gold.dim_course d ON d.course_id = c.course_id;
