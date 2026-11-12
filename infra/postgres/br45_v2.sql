-- Additive migration 002. Existing source rows, marts, checkpoints and alerts are preserved.
CREATE TABLE IF NOT EXISTS analytics.assessment_jobs (
  id text PRIMARY KEY, course_id text NOT NULL, window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL, status text NOT NULL DEFAULT 'PENDING'
    CHECK(status IN ('PENDING','RUNNING','SUCCEEDED','FAILED')),
  requested_revision text, published_revision text, engine text NOT NULL DEFAULT 'spark',
  error text, requested_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz,
  completed_at timestamptz, CHECK(window_start < window_end)
);
CREATE INDEX IF NOT EXISTS assessment_pending ON analytics.assessment_jobs(status,requested_at);
CREATE TABLE IF NOT EXISTS analytics.course_policies (
  course_id text NOT NULL, version integer NOT NULL CHECK(version > 0),
  parameters jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  created_by text NOT NULL, PRIMARY KEY(course_id,version)
);
CREATE TABLE IF NOT EXISTS analytics.intervention_notes (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  alert_id text NOT NULL REFERENCES analytics.dropout_alerts(id),
  actor text NOT NULL, action text NOT NULL, note text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analytics.domain_outbox (
  event_id text PRIMARY KEY, topic text NOT NULL, event_key text NOT NULL,
  payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz
);
CREATE INDEX IF NOT EXISTS domain_pending ON analytics.domain_outbox(created_at)
  WHERE published_at IS NULL;
ALTER TABLE analytics.domain_outbox ADD COLUMN IF NOT EXISTS sequence bigserial;
ALTER TABLE analytics.assessment_jobs ADD COLUMN IF NOT EXISTS required_sequence bigint NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS analytics.risk_dirty (
  student_id text NOT NULL, course_id text NOT NULL,
  PRIMARY KEY(student_id,course_id)
);
CREATE INDEX IF NOT EXISTS clean_student_course ON analytics.clean_rows
  (table_name,(data->>'student_id'),(data->>'course_id')) WHERE NOT deleted;
CREATE INDEX IF NOT EXISTS clean_course ON analytics.clean_rows
  (table_name,(data->>'course_id')) WHERE NOT deleted;
CREATE SCHEMA IF NOT EXISTS br45_benchmark;
CREATE TABLE IF NOT EXISTS br45_benchmark.activity_windows (
  run_id text NOT NULL, engine text NOT NULL, student_id text NOT NULL, course_id text NOT NULL,
  window_start timestamptz NOT NULL, window_end timestamptz NOT NULL,
  activity_count bigint NOT NULL, computed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(run_id,engine,student_id,course_id,window_end)
);
INSERT INTO analytics.schema_migrations(version) VALUES(2) ON CONFLICT DO NOTHING;
