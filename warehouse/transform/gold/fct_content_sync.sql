-- gold.fct_content_sync (full rebuild; accumulating snapshot per content version). BR8: how
-- long a published version takes to be chunked/indexed (cache + search refresh SLA).
INSERT OVERWRITE gold.fct_content_sync
WITH published AS (
  SELECT content_id, version, min(occurred_at) AS published_at
  FROM silver.content_sync_events WHERE event_type LIKE 'content.version_published%'
  GROUP BY content_id, version
),
indexed AS (
  SELECT content_id, version, min(occurred_at) AS indexed_at, max(chunk_count) AS chunk_count
  FROM silver.content_sync_events WHERE event_type LIKE 'content.indexed%'
  GROUP BY content_id, version
)
SELECT coalesce(d.content_key, -1), v.content_id, v.version,
       CASE WHEN v.course_id IS NULL THEN -1 ELSE xxhash64(v.course_id) END,
       coalesce(p.published_at, v.published_at) AS published_at, i.indexed_at, i.chunk_count,
       CAST(i.indexed_at AS DOUBLE) - CAST(coalesce(p.published_at, v.published_at) AS DOUBLE),
       i.indexed_at IS NOT NULL, current_timestamp()
FROM silver.content_versions v
LEFT JOIN published p ON p.content_id = v.content_id AND p.version = v.version
LEFT JOIN indexed i ON i.content_id = v.content_id AND i.version = v.version
LEFT JOIN gold.dim_content d ON d.content_id = v.content_id AND d.version = v.version;
