-- gold.fct_lesson_progress (full rebuild; accumulating snapshot learner x lesson).
-- Completion is conformed across sources: CDC percent_done = 100 OR a telemetry 'completed'
-- event on the lesson's content, whichever happened first.
INSERT OVERWRITE gold.fct_lesson_progress
WITH progress AS (
  SELECT learner_pseudonym, lesson_id, course_id, percent_done, first_progress_at, completed_at, updated_at
  FROM silver.lesson_progress WHERE NOT is_deleted
),
completed_events AS (
  SELECT e.learner_pseudonym, ls.lesson_id, ls.course_id,
         min(e.occurred_at) AS completed_at
  FROM silver.learning_events e
  JOIN silver.lessons ls ON ls.content_id = e.content_id AND NOT ls.is_deleted
  WHERE e.verb = 'completed'
  GROUP BY e.learner_pseudonym, ls.lesson_id, ls.course_id
),
merged AS (
  SELECT coalesce(p.learner_pseudonym, c.learner_pseudonym) AS learner_pseudonym,
         coalesce(p.lesson_id, c.lesson_id) AS lesson_id,
         coalesce(p.course_id, c.course_id) AS course_id,
         greatest(coalesce(p.percent_done, 0), CASE WHEN c.completed_at IS NOT NULL THEN 100 ELSE 0 END) AS percent_done,
         least(p.first_progress_at, c.completed_at) AS first_progress_at,
         least(p.completed_at, c.completed_at) AS completed_at,
         greatest(p.updated_at, c.completed_at) AS last_updated_at
  FROM progress p
  FULL OUTER JOIN completed_events c
    ON c.learner_pseudonym = p.learner_pseudonym AND c.lesson_id = p.lesson_id
)
SELECT coalesce(l.learner_key, -1), xxhash64(m.lesson_id),
       CASE WHEN m.course_id IS NULL THEN -1 ELSE xxhash64(m.course_id) END,
       m.learner_pseudonym, m.lesson_id, m.course_id, m.percent_done, m.percent_done >= 100,
       m.first_progress_at, m.completed_at, m.last_updated_at, current_timestamp()
FROM merged m
LEFT JOIN gold.dim_learner l ON l.learner_pseudonym = m.learner_pseudonym AND l.is_current;
