-- gold.fct_learner_daily_activity (window on activity_date). Verb categories come from
-- dim_activity; engagement_score applies EngagementWeights (passed in from the domain).
INSERT INTO gold.fct_learner_daily_activity
REPLACE WHERE activity_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
WITH daily AS (
  SELECT e.event_date AS activity_date, e.learner_pseudonym, e.course_id,
         count(*)                                                          AS events,
         count(DISTINCT e.session_id)                                      AS sessions,
         count_if(a.engagement_category = 'login')                         AS logins,
         count_if(a.engagement_category = 'view')                          AS views,
         count_if(a.engagement_category = 'attempt')                       AS attempts,
         count_if(a.engagement_category = 'discussion')                    AS discussions,
         count_if(e.verb = 'completed')                                    AS completions,
         count_if(a.video_interaction IS NOT NULL)                         AS video_interactions,
         count(DISTINCT e.content_id)                                      AS distinct_contents,
         array_sort(collect_set(e.platform))                               AS platforms,
         min(e.occurred_at)                                                AS first_event_at,
         max(e.occurred_at)                                                AS last_event_at
  FROM silver.learning_events e
  JOIN gold.dim_activity a ON a.verb = e.verb
  WHERE e.event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
  GROUP BY e.event_date, e.learner_pseudonym, e.course_id
)
SELECT d.activity_date, CAST(date_format(d.activity_date, 'yyyyMMdd') AS INT),
       coalesce(l.learner_key, -1), xxhash64(d.course_id), d.learner_pseudonym, d.course_id,
       d.events, d.sessions, d.logins, d.views, d.attempts, d.discussions, d.completions,
       d.video_interactions, d.distinct_contents,
       round(d.logins * ${w_login} + d.views * ${w_view} + d.attempts * ${w_attempt}
             + d.discussions * ${w_discussion}, 2) AS engagement_score,
       d.platforms, d.first_event_at, d.last_event_at, current_timestamp()
FROM daily d
LEFT JOIN gold.dim_learner l
  ON l.learner_pseudonym = d.learner_pseudonym
 AND d.last_event_at >= l.valid_from AND d.last_event_at < l.valid_to;
