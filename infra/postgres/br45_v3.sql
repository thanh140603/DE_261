-- Job lease fencing, publication provenance and advisor audit fields.
ALTER TABLE analytics.assessment_jobs
  ADD COLUMN IF NOT EXISTS lease_generation bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS source_delta_version bigint,
  ADD COLUMN IF NOT EXISTS publication_id text,
  ADD COLUMN IF NOT EXISTS published_engine text;
ALTER TABLE analytics.intervention_notes ADD COLUMN IF NOT EXISTS idempotency_key text;
CREATE UNIQUE INDEX IF NOT EXISTS intervention_idempotency
  ON analytics.intervention_notes(alert_id,actor,idempotency_key);
ALTER TABLE analytics.course_policies ADD COLUMN IF NOT EXISTS effective_after timestamptz;
ALTER TABLE analytics.dropout_alerts ADD COLUMN IF NOT EXISTS policy_version integer NOT NULL DEFAULT 1;
INSERT INTO analytics.schema_migrations(version) VALUES(3) ON CONFLICT DO NOTHING;
