CREATE SCHEMA IF NOT EXISTS classroom;

CREATE TABLE IF NOT EXISTS classroom.accounts (
    username text PRIMARY KEY,
    student_id text UNIQUE NOT NULL,
    salt bytea NOT NULL,
    password_hash bytea NOT NULL,
    profile text NOT NULL
);

CREATE TABLE IF NOT EXISTS classroom.feedback (
    submission_id text PRIMARY KEY REFERENCES br45.submissions(id),
    student_id text NOT NULL,
    request_id text NOT NULL,
    request_hash text NOT NULL,
    payload jsonb NOT NULL,
    UNIQUE (student_id, request_id)
);
CREATE INDEX IF NOT EXISTS classroom_feedback_student ON classroom.feedback(student_id);

CREATE TABLE IF NOT EXISTS classroom.lesson_progress (
    student_id text NOT NULL,
    lesson_id text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    PRIMARY KEY (student_id, lesson_id)
);

CREATE TABLE IF NOT EXISTS classroom.run (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    next_step bigint NOT NULL DEFAULT 0
);

INSERT INTO analytics.schema_migrations(version) VALUES(4) ON CONFLICT DO NOTHING;
