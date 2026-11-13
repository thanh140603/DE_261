-- BR3-owned durable grading store (Phase 5).
-- Kept out of the LMS public schema so the grading service can evolve and be
-- reset independently. An optional projector (docker compose --profile
-- br13-project) copies these rows into public.submissions/grades for LMS/CDC.
CREATE SCHEMA IF NOT EXISTS grading;

CREATE TABLE IF NOT EXISTS grading.submissions (
  submission_id  TEXT PRIMARY KEY,
  learner_id     TEXT NOT NULL,
  assignment_id  TEXT NOT NULL,
  attempt_number INT NOT NULL DEFAULT 1,
  language       TEXT NOT NULL,
  code_ref       TEXT NOT NULL,
  status         TEXT NOT NULL,
  submitted_at   TIMESTAMPTZ NOT NULL,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS grading.grades (
  submission_id TEXT PRIMARY KEY REFERENCES grading.submissions(submission_id),
  score         NUMERIC(5,2) NOT NULL,
  pass_rate     NUMERIC(5,4) NOT NULL,
  graded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS grading_submissions_learner
  ON grading.submissions(learner_id);
