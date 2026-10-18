-- silver.content_sync_events <- bronze.domain_events (topics content.updated.v1 = ContentVersionPublished,
-- content.indexed.v1 = ContentIndexed). aggregate_id is the content_id.
MERGE INTO silver.content_sync_events AS t
USING (
  SELECT e.event_id, coalesce(e.event_type, topic) AS event_type, e.aggregate_id AS content_id,
         e.version, e.course_id, e.chunk_count, CAST(e.occurred_at AS TIMESTAMP) AS occurred_at,
         ingest_date AS _ingest_date
  FROM (
    SELECT from_json(payload, 'event_id STRING, event_type STRING, aggregate_id STRING, occurred_at STRING, course_id STRING, version INT, chunk_count INT') AS e,
           topic, ingest_date,
           row_number() OVER (PARTITION BY get_json_object(payload, '$.event_id') ORDER BY kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND e.event_id IS NOT NULL AND e.aggregate_id IS NOT NULL AND e.version IS NOT NULL
) AS s
ON t.event_id = s.event_id
WHEN NOT MATCHED THEN INSERT
  (event_id, event_type, content_id, version, course_id, chunk_count, occurred_at, _ingest_date, _processed_at)
  VALUES (s.event_id, s.event_type, s.content_id, s.version, s.course_id, s.chunk_count, s.occurred_at,
          s._ingest_date, current_timestamp());
