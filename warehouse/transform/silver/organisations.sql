-- silver.organisations <- bronze.cdc_events (source_table = 'organisations') via view _src.
-- CDC apply pattern shared by every silver CDC table:
--   1. parse the Debezium row image, 2. keep the latest change per key in this batch (LSN),
--   3. MERGE, updating only when the change is newer than what silver already holds,
--   so replays, overlapping windows and out-of-order micro-batches are all harmless.
MERGE INTO silver.organisations AS t
USING (
  SELECT n.* FROM (
  SELECT r.organisation_id, r.name, r.plan, CAST(r.updated_at AS TIMESTAMP) AS updated_at,
         is_deleted, lsn AS _source_lsn, source_ts AS _source_ts
  FROM (
    SELECT from_json(after, 'organisation_id STRING, name STRING, plan STRING, updated_at STRING') AS r,
           op = 'd' OR get_json_object(after, '$.__deleted') = 'true' AS is_deleted,
           lsn, source_ts,
           row_number() OVER (PARTITION BY get_json_object(after, '$.organisation_id')
                              ORDER BY lsn DESC, kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND r.organisation_id IS NOT NULL
  ) n
  -- only changes newer than silver: replayed / overlapping windows rewrite nothing
  LEFT JOIN silver.organisations cur ON cur.organisation_id = n.organisation_id
  WHERE cur.organisation_id IS NULL OR n._source_lsn > cur._source_lsn
) AS s
ON t.organisation_id = s.organisation_id
WHEN MATCHED AND s._source_lsn > t._source_lsn THEN UPDATE SET
  name = s.name, plan = s.plan, updated_at = s.updated_at, is_deleted = s.is_deleted,
  _source_lsn = s._source_lsn, _source_ts = s._source_ts, _processed_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT
  (organisation_id, name, plan, updated_at, is_deleted, _source_lsn, _source_ts, _processed_at)
  VALUES (s.organisation_id, s.name, s.plan, s.updated_at, s.is_deleted, s._source_lsn, s._source_ts, current_timestamp());
