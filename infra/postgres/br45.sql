-- Additive migration 001. Public LMS tables and other BRs are untouched.
BEGIN;
CREATE SCHEMA IF NOT EXISTS br45;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE TABLE IF NOT EXISTS analytics.schema_migrations (
  version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS br45.courses (
  id text PRIMARY KEY, title text NOT NULL, telemetry_enabled boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS br45.assignments (
  id text PRIMARY KEY, course_id text NOT NULL REFERENCES br45.courses(id), title text NOT NULL,
  deadline timestamptz, required boolean NOT NULL DEFAULT true,
  published_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS br45.questions (
  id text NOT NULL, version integer NOT NULL CHECK(version > 0),
  assignment_id text NOT NULL REFERENCES br45.assignments(id), title text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(id, version)
);
CREATE TABLE IF NOT EXISTS br45.test_cases (
  id text NOT NULL, version integer NOT NULL CHECK(version > 0), question_id text NOT NULL,
  question_version integer NOT NULL, required boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(id, version),
  FOREIGN KEY(question_id,question_version) REFERENCES br45.questions(id,version)
);
CREATE TABLE IF NOT EXISTS br45.enrollments (
  id text PRIMARY KEY, student_id text NOT NULL, course_id text NOT NULL REFERENCES br45.courses(id),
  status text NOT NULL CHECK(status IN ('active','completed','withdrawn')),
  enrolled_at timestamptz NOT NULL, UNIQUE(student_id,course_id)
);
CREATE TABLE IF NOT EXISTS br45.submissions (
  id text PRIMARY KEY, student_id text NOT NULL, course_id text NOT NULL REFERENCES br45.courses(id),
  assignment_id text NOT NULL REFERENCES br45.assignments(id), question_id text NOT NULL,
  question_version integer NOT NULL, submitted_at timestamptz NOT NULL,
  execution_status text NOT NULL CHECK(execution_status IN ('evaluated','pending','infra_error')),
  FOREIGN KEY(question_id,question_version) REFERENCES br45.questions(id,version)
);
CREATE INDEX IF NOT EXISTS br45_submissions_course_time ON br45.submissions(course_id,submitted_at);
CREATE TABLE IF NOT EXISTS br45.evaluations (
  id text PRIMARY KEY, submission_id text NOT NULL REFERENCES br45.submissions(id),
  test_case_id text NOT NULL, test_case_version integer NOT NULL,
  status text NOT NULL CHECK(status IN ('passed','failed','error','timeout','skipped','infra_error')),
  is_valid_evaluation boolean NOT NULL, evaluated_at timestamptz NOT NULL,
  UNIQUE(submission_id,test_case_id,test_case_version),
  FOREIGN KEY(test_case_id,test_case_version) REFERENCES br45.test_cases(id,version)
);
CREATE TABLE IF NOT EXISTS br45.activity_events (
  id text PRIMARY KEY, student_id text NOT NULL, course_id text NOT NULL REFERENCES br45.courses(id),
  event_type text NOT NULL CHECK(event_type IN ('lesson_view','lesson_complete','submission','session')),
  event_time timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS br45_activity_student_time ON br45.activity_events(student_id,course_id,event_time);
CREATE TABLE IF NOT EXISTS br45.clocks (id text PRIMARY KEY, evaluated_at timestamptz NOT NULL);

CREATE TABLE IF NOT EXISTS analytics.raw_changes (
  topic text NOT NULL, partition integer NOT NULL, offset_id bigint NOT NULL,
  change_id text NOT NULL UNIQUE, envelope jsonb, received_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(topic,partition,offset_id)
);
CREATE TABLE IF NOT EXISTS analytics.quarantine (
  change_id text PRIMARY KEY, reason text NOT NULL, payload jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analytics.clean_rows (
  table_name text NOT NULL, row_key text NOT NULL, data jsonb NOT NULL,
  lsn numeric NOT NULL DEFAULT 0, deleted boolean NOT NULL DEFAULT false,
  PRIMARY KEY(table_name,row_key)
);
CREATE INDEX IF NOT EXISTS clean_data_gin ON analytics.clean_rows USING gin(data);
CREATE INDEX IF NOT EXISTS clean_evaluation_join ON analytics.clean_rows
  (table_name,(data->>'submission_id'),(data->>'test_case_id'),(data->>'test_case_version'));
CREATE INDEX IF NOT EXISTS clean_version_join ON analytics.clean_rows
  (table_name,(data->>'id'),(data->>'version'));
CREATE INDEX IF NOT EXISTS clean_test_manifest ON analytics.clean_rows
  (table_name,(data->>'question_id'),(data->>'question_version'));
CREATE TABLE IF NOT EXISTS analytics.outbox (
  event_id text PRIMARY KEY, payload jsonb NOT NULL, published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS outbox_pending ON analytics.outbox(created_at) WHERE published_at IS NULL;
CREATE TABLE IF NOT EXISTS analytics.pipeline_state (
  key text PRIMARY KEY, value jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analytics.mart_question_pass_statistics (
  id text PRIMARY KEY, course_id text NOT NULL, assignment_id text NOT NULL,
  question_id text NOT NULL, question_version integer NOT NULL,
  window_start timestamptz NOT NULL, window_end timestamptz NOT NULL,
  data jsonb NOT NULL, computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS question_mart_course ON analytics.mart_question_pass_statistics(course_id,assignment_id,window_end);
CREATE TABLE IF NOT EXISTS analytics.mart_test_case_pass_statistics (
  id text PRIMARY KEY, course_id text NOT NULL, assignment_id text NOT NULL,
  question_id text NOT NULL, question_version integer NOT NULL,
  test_case_id text NOT NULL, test_case_version integer NOT NULL,
  window_start timestamptz NOT NULL, window_end timestamptz NOT NULL,
  data jsonb NOT NULL, computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS case_mart_course ON analytics.mart_test_case_pass_statistics(course_id,question_id,window_end);
CREATE TABLE IF NOT EXISTS analytics.mart_question_anomalies (
  id text PRIMARY KEY, course_id text NOT NULL, assignment_id text NOT NULL,
  question_id text NOT NULL, state text NOT NULL, severity text NOT NULL,
  window_start timestamptz NOT NULL, window_end timestamptz NOT NULL, data jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS analytics.assessment_materializations (
  id text PRIMARY KEY, source_revision text NOT NULL,
  computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS anomalies_course ON analytics.mart_question_anomalies(course_id,severity,window_end);
CREATE TABLE IF NOT EXISTS analytics.activity_windows (
  student_id text NOT NULL, course_id text NOT NULL, window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL, activity_count bigint NOT NULL,
  computed_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(student_id,course_id,window_end)
);
CREATE TABLE IF NOT EXISTS analytics.risk_state (
  student_id text NOT NULL, course_id text NOT NULL, score integer NOT NULL,
  level text NOT NULL, eligible boolean NOT NULL, evaluated_at timestamptz NOT NULL,
  data jsonb NOT NULL, computed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(student_id,course_id)
);
CREATE TABLE IF NOT EXISTS analytics.risk_history (
  id text PRIMARY KEY, student_id text NOT NULL, course_id text NOT NULL,
  evaluated_at timestamptz NOT NULL, score integer NOT NULL, data jsonb NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS risk_history_student ON analytics.risk_history(student_id,course_id,evaluated_at);
CREATE TABLE IF NOT EXISTS analytics.dropout_alerts (
  id text PRIMARY KEY, student_id text NOT NULL, course_id text NOT NULL,
  score integer NOT NULL, level text NOT NULL, reasons jsonb NOT NULL,
  status text NOT NULL CHECK(status IN ('NEW','ACKNOWLEDGED','RESOLVED')),
  evaluated_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  acknowledged_at timestamptz, acknowledged_by text, resolved_at timestamptz, resolved_by text
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_alert ON analytics.dropout_alerts(student_id,course_id) WHERE status <> 'RESOLVED';
INSERT INTO analytics.schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING;
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['courses','assignments','questions','test_cases','enrollments','submissions','evaluations','activity_events','clocks'] LOOP
    EXECUTE format('ALTER TABLE br45.%I REPLICA IDENTITY FULL',t);
  END LOOP;
END $$;
COMMIT;
