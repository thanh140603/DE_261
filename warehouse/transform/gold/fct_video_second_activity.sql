-- gold.fct_video_second_activity (window on activity_date). BR7: play / pause / seek per
-- second of the content version that was live when the event happened. Positions beyond
-- the video length are clamped to its last second (same rule as BuildVideoHeatmap).
INSERT INTO gold.fct_video_second_activity
REPLACE WHERE activity_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
SELECT e.event_date, CAST(date_format(e.event_date, 'yyyyMMdd') AS INT),
       coalesce(c.content_key, -1), e.content_id, c.version,
       CASE WHEN c.duration_sec IS NULL THEN e.video_position_sec
            ELSE least(e.video_position_sec, greatest(c.duration_sec - 1, 0)) END AS second,
       count_if(a.video_interaction = 'play'), count_if(a.video_interaction = 'pause'),
       count_if(a.video_interaction = 'seek'), count(DISTINCT e.learner_pseudonym),
       current_timestamp()
FROM silver.learning_events e
JOIN gold.dim_activity a ON a.verb = e.verb AND a.video_interaction IS NOT NULL
LEFT JOIN gold.dim_content c
  ON c.content_id = e.content_id
 AND e.occurred_at >= c.valid_from AND e.occurred_at < c.valid_to
WHERE e.event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
  AND e.content_id IS NOT NULL AND e.video_position_sec IS NOT NULL
GROUP BY 1, 2, 3, 4, 5, 6;
