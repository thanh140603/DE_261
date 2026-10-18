-- gold.fct_risk_score_daily (window on score_date). Daily snapshot of the Flink risk score.
INSERT INTO gold.fct_risk_score_daily
REPLACE WHERE score_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
WITH scores AS (
  SELECT score_date, learner_pseudonym, course_id,
         max(risk_score) AS max_risk_score,
         max_by(risk_score, computed_at) AS last_risk_score,
         count(*) AS score_updates,
         max(computed_at) AS last_computed_at
  FROM silver.risk_scores
  WHERE score_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
  GROUP BY score_date, learner_pseudonym, course_id
),
alerts AS (
  SELECT CAST(alerted_at AS DATE) AS alert_date, learner_pseudonym, course_id, count(*) AS alerts
  FROM silver.dropout_alerts GROUP BY 1, 2, 3
)
SELECT s.score_date, CAST(date_format(s.score_date, 'yyyyMMdd') AS INT),
       coalesce(l.learner_key, -1), xxhash64(s.course_id), s.learner_pseudonym, s.course_id,
       s.max_risk_score, s.last_risk_score, s.score_updates, coalesce(a.alerts, 0),
       s.last_risk_score >= ${risk_alert_threshold}, current_timestamp()
FROM scores s
LEFT JOIN alerts a
  ON a.alert_date = s.score_date AND a.learner_pseudonym = s.learner_pseudonym AND a.course_id = s.course_id
LEFT JOIN gold.dim_learner l
  ON l.learner_pseudonym = s.learner_pseudonym
 AND s.last_computed_at >= l.valid_from AND s.last_computed_at < l.valid_to;
