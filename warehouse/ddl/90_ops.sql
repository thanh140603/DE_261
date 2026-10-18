-- OPS: pipeline observability, written by the warehouse runner (platform/warehouse).

CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
  run_id        STRING    NOT NULL,
  model         STRING    NOT NULL COMMENT 'Table built, e.g. gold.fct_submission',
  layer         STRING    NOT NULL,
  run_date      DATE      NOT NULL,
  strategy      STRING    NOT NULL COMMENT 'full | window | python',
  window_start  DATE,
  window_end    DATE,
  status        STRING    NOT NULL COMMENT 'success | failed',
  rows_written  BIGINT,
  table_version BIGINT    COMMENT 'Delta version after the write (time travel / audit)',
  started_at    TIMESTAMP NOT NULL,
  finished_at   TIMESTAMP NOT NULL,
  error         STRING
) USING DELTA
PARTITIONED BY (run_date)
LOCATION '${lakehouse_root}/ops/pipeline_runs';

CREATE TABLE IF NOT EXISTS ops.dq_results (
  run_id      STRING    NOT NULL,
  check_name  STRING    NOT NULL,
  model       STRING    NOT NULL,
  severity    STRING    NOT NULL COMMENT 'error stops the pipeline, warn is recorded only',
  violations  BIGINT    NOT NULL,
  passed      BOOLEAN   NOT NULL,
  run_date    DATE      NOT NULL,
  checked_at  TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (run_date)
LOCATION '${lakehouse_root}/ops/dq_results';
