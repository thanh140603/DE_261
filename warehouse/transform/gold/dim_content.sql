-- gold.dim_content (SCD2 by content version, full rebuild from the version history).
-- The first known version is valid from 1900-01-01 so every earlier event resolves to it;
-- each later version starts when it was published and ends when the next one was.
-- content_key = xxhash64(content_id, valid_from): an inferred member (content seen in telemetry
-- before its CDC row) gets the same key its first real version will get.
INSERT OVERWRITE gold.dim_content
WITH v AS (
  SELECT *,
         row_number() OVER (PARTITION BY content_id ORDER BY version) AS seq,
         lead(published_at) OVER (PARTITION BY content_id ORDER BY version) AS next_published_at
  FROM silver.content_versions
),
versions AS (
  SELECT content_id, version, course_id, content_type, title, duration_sec, object_key,
         CASE WHEN seq = 1 THEN TIMESTAMP'1900-01-01 00:00:00' ELSE published_at END AS valid_from,
         coalesce(next_published_at, TIMESTAMP'9999-12-31 00:00:00') AS valid_to,
         next_published_at IS NULL AS is_current
  FROM v
),
refs AS (
  SELECT content_id FROM silver.learning_events
  WHERE content_id IS NOT NULL AND event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}'
  UNION SELECT content_id FROM silver.lessons WHERE content_id IS NOT NULL
  UNION SELECT content_id FROM gold.dim_content WHERE is_inferred
)
SELECT xxhash64(content_id, valid_from), content_id, version, course_id, content_type, title,
       duration_sec, object_key, valid_from, valid_to, is_current, false, current_timestamp()
FROM versions
UNION ALL
SELECT xxhash64(r.content_id, TIMESTAMP'1900-01-01 00:00:00'), r.content_id, NULL, NULL, NULL, NULL,
       NULL, NULL, TIMESTAMP'1900-01-01 00:00:00', TIMESTAMP'9999-12-31 00:00:00', true, true,
       current_timestamp()
FROM refs r LEFT ANTI JOIN (SELECT DISTINCT content_id FROM versions) s ON s.content_id = r.content_id
UNION ALL
SELECT -1, 'n/a', NULL, NULL, NULL, 'Not content-related', NULL, NULL,
       TIMESTAMP'1900-01-01 00:00:00', TIMESTAMP'9999-12-31 00:00:00', true, false, current_timestamp();
