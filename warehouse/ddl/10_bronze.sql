-- BRONZE: one row per landed Kafka record, written only by the Spark landing job
-- (entrypoints/streaming/lakehouse_landing_job.py). Append-only, never updated, so any silver
-- or gold table can be rebuilt by replaying bronze. Raw identifiers live here and nowhere else.

CREATE TABLE IF NOT EXISTS bronze.telemetry_raw (
  event_id         STRING    COMMENT 'Client event id (idempotency key); NULL when the payload has none',
  learner_id       STRING    COMMENT 'RAW learner id - PII, pseudonymised before silver',
  schema_version   STRING    COMMENT 'Client payload schema version, e.g. 1.0 / 1.1',
  payload          STRING    COMMENT 'Client JSON payload exactly as received',
  kafka_topic      STRING,
  kafka_partition  INT,
  kafka_offset     BIGINT,
  received_at      TIMESTAMP COMMENT 'Broker timestamp = ingestion time (lateness = received_at - occurred_at)',
  ingest_date      DATE      COMMENT 'Partition: date of received_at (UTC)',
  _landed_at       TIMESTAMP COMMENT 'When the landing job wrote the row'
) USING DELTA
PARTITIONED BY (ingest_date)
LOCATION '${lakehouse_root}/bronze/telemetry_raw'
COMMENT 'Clickstream telemetry from web/android/ios (topic telemetry.events.raw.v1).'
TBLPROPERTIES ('edu.pii' = 'raw', 'edu.retention_days' = '30', 'edu.owner' = 'telemetry');

CREATE TABLE IF NOT EXISTS bronze.telemetry_dlq (
  event_id         STRING,
  learner_id       STRING    COMMENT 'RAW learner id - PII',
  payload          STRING,
  reason           STRING    COMMENT 'Validation / migration / vocabulary error',
  rejected_by      STRING    COMMENT 'flink (fast path topic telemetry.events.dlq.v1) | spark (bronze->silver)',
  received_at      TIMESTAMP,
  ingest_date      DATE,
  _landed_at       TIMESTAMP
) USING DELTA
PARTITIONED BY (ingest_date)
LOCATION '${lakehouse_root}/bronze/telemetry_dlq'
COMMENT 'Telemetry that could not become a silver event. Replayable after a fix.'
TBLPROPERTIES ('edu.pii' = 'raw', 'edu.retention_days' = '30', 'edu.owner' = 'telemetry');

CREATE TABLE IF NOT EXISTS bronze.cdc_events (
  source_table     STRING    COMMENT 'LMS table name (enrollments, submissions, ...)',
  op               STRING    COMMENT 'Debezium op: r snapshot, c insert, u update, d delete',
  lsn              BIGINT    COMMENT 'Postgres WAL position - ordering key per row',
  tx_id            BIGINT,
  source_ts        TIMESTAMP COMMENT 'Commit time in the OLTP database',
  record_key       STRING    COMMENT 'Kafka key (primary key JSON)',
  after            STRING    COMMENT 'Row image after the change (ExtractNewRecordState); deletes carry __deleted=true',
  kafka_partition  INT,
  kafka_offset     BIGINT,
  ingest_date      DATE,
  _landed_at       TIMESTAMP
) USING DELTA
PARTITIONED BY (source_table, ingest_date)
LOCATION '${lakehouse_root}/bronze/cdc_events'
COMMENT 'Row-level change stream of the LMS PostgreSQL database (Debezium topics cdc.lms.public.*).'
TBLPROPERTIES ('edu.pii' = 'raw', 'edu.retention_days' = '90', 'edu.owner' = 'platform');

CREATE TABLE IF NOT EXISTS bronze.domain_events (
  topic            STRING    COMMENT 'Kafka topic = event type and version',
  event_id         STRING    COMMENT 'payload.event_id when present',
  event_key        STRING    COMMENT 'Kafka key (aggregate id)',
  payload          STRING    COMMENT 'Event JSON exactly as published',
  kafka_partition  INT,
  kafka_offset     BIGINT,
  kafka_timestamp  TIMESTAMP,
  ingest_date      DATE,
  _landed_at       TIMESTAMP
) USING DELTA
PARTITIONED BY (topic, ingest_date)
LOCATION '${lakehouse_root}/bronze/domain_events'
COMMENT 'Business and pipeline events (grading.*, risk.*, notification.*, content.*, lms.*, features.*).'
TBLPROPERTIES ('edu.pii' = 'raw', 'edu.retention_days' = '90', 'edu.owner' = 'platform');
