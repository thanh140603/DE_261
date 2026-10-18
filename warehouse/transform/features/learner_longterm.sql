-- features.learner_longterm (BR2 batch branch, snapshot partition as_of_date = run_date).
-- ComputeBatchFeatures semantics over the 30 days before the end of run_date, for every
-- learner with activity in that window:
--   completion_rate_30d = min(1, distinct completed (course, content) / lessons of the courses touched)
--   avg_pass_rate_30d   = mean pass rate of graded submissions (0 when none)
--   active_days_30d     = distinct active days; preferred_platform = most used platform
--   skill_mastery       = per course skill, mean of graded pass rates and 1.0 per completed item
INSERT INTO features.learner_longterm
REPLACE WHERE as_of_date = DATE'${run_date}'
WITH bounds AS (
  SELECT CAST(date_add(DATE'${run_date}', 1) AS TIMESTAMP) AS as_of,
         CAST(date_add(DATE'${run_date}', 1) AS TIMESTAMP) - INTERVAL ${feature_window_days} DAYS AS since
),
ev AS (
  SELECT f.* FROM gold.fct_learning_event f CROSS JOIN bounds b
  WHERE f.event_date BETWEEN CAST(b.since AS DATE) AND DATE'${run_date}'
    AND f.occurred_at >= b.since AND f.occurred_at < b.as_of
),
completed AS (
  SELECT DISTINCT learner_pseudonym, course_id, content_id FROM ev WHERE verb = 'completed'
),
courses_touched AS (
  SELECT e.learner_pseudonym, sum(coalesce(c.lesson_count, 0)) AS total_lessons
  FROM (SELECT DISTINCT learner_pseudonym, course_id FROM ev) e
  LEFT JOIN gold.dim_course c ON c.course_id = e.course_id
  GROUP BY e.learner_pseudonym
),
graded AS (
  SELECT s.learner_pseudonym, s.course_id, s.pass_rate
  FROM gold.fct_submission s CROSS JOIN bounds b
  WHERE s.pass_rate IS NOT NULL AND s.graded_at >= b.since AND s.graded_at < b.as_of
),
platform_rank AS (
  SELECT learner_pseudonym, platform,
         row_number() OVER (PARTITION BY learner_pseudonym ORDER BY count(*) DESC, platform) AS rn
  FROM ev GROUP BY learner_pseudonym, platform
),
mastery AS (
  SELECT learner_pseudonym, map_from_entries(collect_list(struct(skill, round(avg_value, 2)))) AS skill_mastery
  FROM (
    SELECT x.learner_pseudonym, coalesce(c.skill, 'general') AS skill, avg(x.value) AS avg_value
    FROM (
      SELECT learner_pseudonym, course_id, pass_rate AS value FROM graded
      UNION ALL
      SELECT learner_pseudonym, course_id, 1.0 AS value FROM completed
    ) x
    LEFT JOIN gold.dim_course c ON c.course_id = x.course_id
    GROUP BY x.learner_pseudonym, coalesce(c.skill, 'general')
  ) GROUP BY learner_pseudonym
),
base AS (
  SELECT learner_pseudonym, count(DISTINCT event_date) AS active_days FROM ev GROUP BY learner_pseudonym
)
SELECT DATE'${run_date}', b.learner_pseudonym,
       round(least(1.0, coalesce(cp.n, 0) / greatest(coalesce(ct.total_lessons, 0), 1)), 3),
       round(coalesce(g.avg_pass_rate, 0.0), 3),
       CAST(b.active_days AS INT), p.platform, coalesce(m.skill_mastery, CAST(map() AS MAP<STRING, DOUBLE>)),
       ${feature_version}, current_timestamp()
FROM base b
LEFT JOIN (SELECT learner_pseudonym, count(*) AS n FROM completed GROUP BY learner_pseudonym) cp
  ON cp.learner_pseudonym = b.learner_pseudonym
LEFT JOIN courses_touched ct ON ct.learner_pseudonym = b.learner_pseudonym
LEFT JOIN (SELECT learner_pseudonym, avg(pass_rate) AS avg_pass_rate FROM graded GROUP BY learner_pseudonym) g
  ON g.learner_pseudonym = b.learner_pseudonym
LEFT JOIN platform_rank p ON p.learner_pseudonym = b.learner_pseudonym AND p.rn = 1
LEFT JOIN mastery m ON m.learner_pseudonym = b.learner_pseudonym;
