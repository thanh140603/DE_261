-- Ratios published to dashboards and features stay within [0, 1].
SELECT sum(n) AS violations FROM (
  SELECT count(*) AS n FROM mart.assessment_item_stats
   WHERE as_of_date = DATE'${run_date}' AND (pass_rate NOT BETWEEN 0 AND 1 OR assignment_median_pass_rate NOT BETWEEN 0 AND 1)
  UNION ALL SELECT count(*) FROM mart.org_progress
   WHERE as_of_date = DATE'${run_date}' AND (completion_rate NOT BETWEEN 0 AND 1 OR avg_mastery NOT BETWEEN 0 AND 1)
  UNION ALL SELECT count(*) FROM mart.video_heatmap WHERE intensity NOT BETWEEN 0 AND 1
  UNION ALL SELECT count(*) FROM features.learner_longterm
   WHERE as_of_date = DATE'${run_date}' AND (completion_rate_30d NOT BETWEEN 0 AND 1 OR avg_pass_rate_30d NOT BETWEEN 0 AND 1)
);
