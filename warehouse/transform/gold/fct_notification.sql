-- gold.fct_notification (window on event_date). Recipients that are not learners (advisors)
-- resolve to the unknown learner member (-1).
INSERT INTO gold.fct_notification
REPLACE WHERE event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
SELECT n.event_id, n.event_date, CAST(date_format(n.event_date, 'yyyyMMdd') AS INT),
       coalesce(l.learner_key, -1), n.notification_id, n.channel, n.outcome, n.reason, n.occurred_at,
       current_timestamp()
FROM silver.notifications n
LEFT JOIN gold.dim_learner l
  ON l.learner_pseudonym = n.recipient_pseudonym
 AND n.occurred_at >= l.valid_from AND n.occurred_at < l.valid_to
WHERE n.event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}';
