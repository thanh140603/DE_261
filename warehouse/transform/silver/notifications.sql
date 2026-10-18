-- silver.notifications <- bronze.domain_events (topics notification.dispatched.v1 and
-- notification.suppressed.v1). recipient_id is pseudonymised.
MERGE INTO silver.notifications AS t
USING (
  SELECT e.event_id, e.aggregate_id AS notification_id, pseudonymize(e.recipient_id) AS recipient_pseudonym,
         e.channel,
         CASE WHEN topic LIKE 'notification.suppressed%' THEN 'suppressed' ELSE 'dispatched' END AS outcome,
         e.reason, CAST(e.occurred_at AS TIMESTAMP) AS occurred_at,
         CAST(CAST(e.occurred_at AS TIMESTAMP) AS DATE) AS event_date, ingest_date AS _ingest_date
  FROM (
    SELECT from_json(payload, 'event_id STRING, aggregate_id STRING, occurred_at STRING, recipient_id STRING, channel STRING, reason STRING') AS e,
           topic, ingest_date,
           row_number() OVER (PARTITION BY get_json_object(payload, '$.event_id') ORDER BY kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND e.event_id IS NOT NULL AND e.recipient_id IS NOT NULL
) AS s
ON t.event_id = s.event_id AND t.event_date = s.event_date
WHEN NOT MATCHED THEN INSERT
  (event_id, notification_id, recipient_pseudonym, channel, outcome, reason, occurred_at, event_date,
   _ingest_date, _processed_at)
  VALUES (s.event_id, s.notification_id, s.recipient_pseudonym, s.channel, s.outcome, s.reason,
          s.occurred_at, s.event_date, s._ingest_date, current_timestamp());
