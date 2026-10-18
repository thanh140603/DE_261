-- mart.engagement_trend (BR8, snapshot partition as_of_date = run_date).
-- ComputeEngagementTrend semantics: n consecutive 7-day windows ending at the end of run_date;
-- every learner active in any window gets a dense series (0 for silent weeks).
-- is_declining (EngagementPolicy): last three windows a, b, c with a > 0,
-- b <= a * (1 - decline_ratio) and c <= b * (1 - decline_ratio).
INSERT INTO mart.engagement_trend
REPLACE WHERE as_of_date = DATE'${run_date}'
WITH bounds AS (SELECT date_add(DATE'${run_date}', 1) AS end_excl),
activity AS (
  SELECT d.course_id, d.learner_pseudonym,
         ${engagement_weeks} - CAST(floor((datediff(b.end_excl, d.activity_date) - 1) / 7) AS INT) AS week_index,
         d.engagement_score
  FROM gold.fct_learner_daily_activity d CROSS JOIN bounds b
  WHERE d.activity_date >= date_sub(b.end_excl, 7 * ${engagement_weeks}) AND d.activity_date < b.end_excl
),
learners AS (SELECT DISTINCT course_id, learner_pseudonym FROM activity),
grid AS (
  SELECT l.course_id, l.learner_pseudonym, w AS week_index
  FROM learners l LATERAL VIEW explode(sequence(1, ${engagement_weeks})) x AS w
),
series AS (
  SELECT g.course_id, g.learner_pseudonym, g.week_index,
         round(coalesce(sum(a.engagement_score), 0.0), 2) AS score
  FROM grid g
  LEFT JOIN activity a
    ON a.course_id = g.course_id AND a.learner_pseudonym = g.learner_pseudonym AND a.week_index = g.week_index
  GROUP BY g.course_id, g.learner_pseudonym, g.week_index
),
flagged AS (
  SELECT s.*,
         s.score - lag(s.score) OVER (PARTITION BY course_id, learner_pseudonym ORDER BY week_index) AS delta,
         max(CASE WHEN week_index = ${engagement_weeks} - 2 THEN score END) OVER (PARTITION BY course_id, learner_pseudonym) AS a,
         max(CASE WHEN week_index = ${engagement_weeks} - 1 THEN score END) OVER (PARTITION BY course_id, learner_pseudonym) AS b,
         max(CASE WHEN week_index = ${engagement_weeks}     THEN score END) OVER (PARTITION BY course_id, learner_pseudonym) AS c,
         round(avg(score) OVER (PARTITION BY course_id, week_index), 2) AS course_avg
  FROM series s
)
SELECT DATE'${run_date}', f.course_id, f.learner_pseudonym, f.week_index,
       date_sub(b.end_excl, 7 * (${engagement_weeks} - f.week_index + 1)) AS week_start,
       f.score, round(f.delta, 2),
       coalesce(f.a > 0 AND f.b <= f.a * (1 - ${decline_ratio}) AND f.c <= f.b * (1 - ${decline_ratio}), false),
       f.course_avg, ${decline_ratio}, current_timestamp()
FROM flagged f CROSS JOIN bounds b;
