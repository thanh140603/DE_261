-- Minimal LMS OLTP schema for local CDC testing (BR5 source). Production schema is
-- owned by the LMS team; only the tables listed in the Debezium connector are captured.
-- TODO: extend with realistic seed data generator (scripts/seed_oltp.py).

CREATE TABLE IF NOT EXISTS enrollments (
  enrollment_id   UUID PRIMARY KEY,
  learner_id      UUID NOT NULL,
  course_id       UUID NOT NULL,
  organisation_id UUID,
  status          TEXT NOT NULL CHECK (status IN ('active','completed','dropped')),
  enrolled_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lesson_progress (
  learner_id   UUID NOT NULL,
  lesson_id    UUID NOT NULL,
  course_id    UUID NOT NULL,
  percent_done SMALLINT NOT NULL CHECK (percent_done BETWEEN 0 AND 100),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (learner_id, lesson_id)
);

CREATE TABLE IF NOT EXISTS submissions (
  submission_id  UUID PRIMARY KEY,
  learner_id     UUID NOT NULL,
  assignment_id  UUID NOT NULL,
  attempt_number INT NOT NULL DEFAULT 1,
  language       TEXT NOT NULL,
  code_ref       TEXT NOT NULL,
  status         TEXT NOT NULL,
  submitted_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS grades (
  submission_id UUID PRIMARY KEY REFERENCES submissions(submission_id),
  score         NUMERIC(5,2) NOT NULL,
  pass_rate     NUMERIC(5,4) NOT NULL,
  graded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS course_content (
  content_id   UUID PRIMARY KEY,
  course_id    UUID NOT NULL,
  content_type TEXT NOT NULL,
  title        TEXT NOT NULL,
  version      INT NOT NULL DEFAULT 1,
  object_key   TEXT NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Debezium needs REPLICA IDENTITY FULL to emit "before" images for updates/deletes.
ALTER TABLE enrollments     REPLICA IDENTITY FULL;
ALTER TABLE lesson_progress REPLICA IDENTITY FULL;
ALTER TABLE submissions     REPLICA IDENTITY FULL;
ALTER TABLE grades          REPLICA IDENTITY FULL;
ALTER TABLE course_content  REPLICA IDENTITY FULL;
