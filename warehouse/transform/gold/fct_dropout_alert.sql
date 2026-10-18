-- gold.fct_dropout_alert (full rebuild). Outcome labels measure alert precision (BR5); they
-- stay NULL until their observation window (30 d / 7 d after the alert) has elapsed at run_date.
INSERT OVERWRITE gold.fct_dropout_alert
SELECT a.alert_id, CAST(a.alerted_at AS DATE), CAST(date_format(a.alerted_at, 'yyyyMMdd') AS INT),
       coalesce(l.learner_key, -1), xxhash64(a.course_id), a.learner_pseudonym, a.course_id,
       a.risk_score, a.top_signals, a.alerted_at,
       CASE WHEN e.dropped_at IS NOT NULL AND e.dropped_at >= a.alerted_at
                 AND e.dropped_at < a.alerted_at + INTERVAL 30 DAYS THEN true
            WHEN date_add(CAST(a.alerted_at AS DATE), 30) <= DATE'${run_date}' THEN false
       END AS dropped_within_30d,
       CASE WHEN act.active_days > 0 THEN true
            WHEN date_add(CAST(a.alerted_at AS DATE), 7) <= DATE'${run_date}' THEN false
       END AS active_after_alert,
       current_timestamp()
FROM silver.dropout_alerts a
LEFT JOIN silver.enrollments e ON e.learner_pseudonym = a.learner_pseudonym AND e.course_id = a.course_id
LEFT JOIN (
  SELECT al.alert_id, count(*) AS active_days
  FROM silver.dropout_alerts al
  JOIN gold.fct_learner_daily_activity d
    ON d.learner_pseudonym = al.learner_pseudonym AND d.course_id = al.course_id
   AND d.activity_date > CAST(al.alerted_at AS DATE)
   AND d.activity_date <= date_add(CAST(al.alerted_at AS DATE), 7)
  GROUP BY al.alert_id
) act ON act.alert_id = a.alert_id
LEFT JOIN gold.dim_learner l
  ON l.learner_pseudonym = a.learner_pseudonym
 AND a.alerted_at >= l.valid_from AND a.alerted_at < l.valid_to;
