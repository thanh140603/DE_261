-- mart.video_heatmap (BR7, full replace). BuildVideoHeatmap semantics: a dense grid with one
-- row for every second of every video version watched in the trailing window, counting
-- play / pause / seek and distinct learners per second. Built from the event-level fact so
-- unique_learners is exact over the whole window (daily uniques are not additive).
INSERT OVERWRITE mart.video_heatmap
WITH ev AS (
  SELECT f.content_key, f.learner_pseudonym, a.video_interaction,
         CASE WHEN c.duration_sec IS NULL THEN f.video_position_sec
              ELSE least(f.video_position_sec, greatest(c.duration_sec - 1, 0)) END AS second
  FROM gold.fct_learning_event f
  JOIN gold.dim_activity a ON a.activity_key = f.activity_key AND a.video_interaction IS NOT NULL
  JOIN gold.dim_content c ON c.content_key = f.content_key
  WHERE f.event_date BETWEEN date_sub(DATE'${run_date}', ${heatmap_window_days} - 1) AND DATE'${run_date}'
    AND f.video_position_sec IS NOT NULL AND f.content_key <> -1
),
counts AS (
  SELECT content_key, second,
         count_if(video_interaction = 'play') AS play_count,
         count_if(video_interaction = 'pause') AS pause_count,
         count_if(video_interaction = 'seek') AS seek_count,
         count(DISTINCT learner_pseudonym) AS unique_learners
  FROM ev GROUP BY content_key, second
),
grid AS (
  SELECT c.content_key, c.content_id, c.version, c.content_title, c.course_id, c.duration_sec,
         explode(sequence(0, greatest(coalesce(c.duration_sec, m.max_second + 1), 1) - 1)) AS second
  FROM gold.dim_content c
  JOIN (SELECT content_key, max(second) AS max_second FROM counts GROUP BY content_key) m
    ON m.content_key = c.content_key
),
dense AS (
  SELECT g.*, coalesce(k.play_count, 0) AS play_count, coalesce(k.pause_count, 0) AS pause_count,
         coalesce(k.seek_count, 0) AS seek_count, coalesce(k.unique_learners, 0) AS unique_learners
  FROM grid g LEFT JOIN counts k ON k.content_key = g.content_key AND k.second = g.second
)
SELECT DATE'${run_date}', ${heatmap_window_days}, content_id, version, content_title, course_id,
       duration_sec, second, play_count, pause_count, seek_count, unique_learners,
       round(coalesce((play_count + pause_count + seek_count)
             / nullif(max(play_count + pause_count + seek_count) OVER (PARTITION BY content_key), 0), 0.0), 4),
       current_timestamp()
FROM dense;
