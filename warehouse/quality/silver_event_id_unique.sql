-- silver.learning_events must be unique on event_id (dedup of mobile re-sends).
SELECT count(*) - count(DISTINCT event_id) AS violations
FROM silver.learning_events
WHERE event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}';
