-- LMS OLTP schema for local CDC (source of BR5 signals and of the warehouse dimensions).
-- Production schema is owned by the LMS team; only the tables listed in the Debezium connector
-- are captured (infra/debezium/postgres-connector.json -> topics cdc.lms.public.<table>).
-- Ids are TEXT to match the demo reference data (l-001, c-sql-101, ...).

-- --- reference data (-> silver.* -> gold.dim_*) ------------------------------------------
CREATE TABLE IF NOT EXISTS organisations (
  organisation_id TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  plan            TEXT NOT NULL DEFAULT 'team',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS learners (
  learner_id      TEXT PRIMARY KEY,
  organisation_id TEXT REFERENCES organisations(organisation_id),
  advisor_id      TEXT,
  email           TEXT NOT NULL,          -- PII: dropped before silver
  full_name       TEXT NOT NULL,          -- PII: dropped before silver
  country_code    TEXT,
  signed_up_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS courses (
  course_id             TEXT PRIMARY KEY,
  title                 TEXT NOT NULL,
  skill                 TEXT NOT NULL,
  level                 TEXT NOT NULL DEFAULT 'beginner',
  owner_organisation_id TEXT,
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lessons (
  lesson_id  TEXT PRIMARY KEY,
  course_id  TEXT NOT NULL REFERENCES courses(course_id),
  content_id TEXT,
  title      TEXT NOT NULL,
  ordinal    INT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS course_content (
  content_id   TEXT PRIMARY KEY,
  course_id    TEXT NOT NULL,
  content_type TEXT NOT NULL,
  title        TEXT NOT NULL,
  version      INT NOT NULL DEFAULT 1,
  object_key   TEXT NOT NULL,
  duration_sec INT,                       -- video length; NULL for slides / exercises
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS assignments (
  assignment_id TEXT PRIMARY KEY,
  course_id     TEXT NOT NULL REFERENCES courses(course_id),
  lesson_id     TEXT,
  title         TEXT NOT NULL,
  language      TEXT NOT NULL,
  due_at        TIMESTAMPTZ,
  max_score     NUMERIC(6,2) NOT NULL DEFAULT 100,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS test_cases (
  assignment_id TEXT NOT NULL REFERENCES assignments(assignment_id),
  test_case_id  TEXT NOT NULL,
  name          TEXT NOT NULL,
  weight        NUMERIC(5,2) NOT NULL DEFAULT 1,
  is_hidden     BOOLEAN NOT NULL DEFAULT false,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (assignment_id, test_case_id)
);

-- --- transactional state (-> silver.* -> gold.fct_*, BR5 risk signals) ---------------------
CREATE TABLE IF NOT EXISTS enrollments (
  enrollment_id   TEXT PRIMARY KEY,
  learner_id      TEXT NOT NULL,
  course_id       TEXT NOT NULL,
  organisation_id TEXT,
  status          TEXT NOT NULL CHECK (status IN ('active','completed','dropped')),
  enrolled_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lesson_progress (
  learner_id   TEXT NOT NULL,
  lesson_id    TEXT NOT NULL,
  course_id    TEXT NOT NULL,
  percent_done SMALLINT NOT NULL CHECK (percent_done BETWEEN 0 AND 100),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (learner_id, lesson_id)
);

CREATE TABLE IF NOT EXISTS submissions (
  submission_id  TEXT PRIMARY KEY,
  learner_id     TEXT NOT NULL,
  assignment_id  TEXT NOT NULL,
  attempt_number INT NOT NULL DEFAULT 1,
  language       TEXT NOT NULL,
  code_ref       TEXT NOT NULL,
  status         TEXT NOT NULL,
  submitted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS grades (
  submission_id TEXT PRIMARY KEY REFERENCES submissions(submission_id),
  score         NUMERIC(5,2) NOT NULL,
  pass_rate     NUMERIC(5,4) NOT NULL,
  graded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Debezium needs REPLICA IDENTITY FULL to emit complete row images for updates/deletes.
ALTER TABLE organisations   REPLICA IDENTITY FULL;
ALTER TABLE learners        REPLICA IDENTITY FULL;
ALTER TABLE courses         REPLICA IDENTITY FULL;
ALTER TABLE lessons         REPLICA IDENTITY FULL;
ALTER TABLE course_content  REPLICA IDENTITY FULL;
ALTER TABLE assignments     REPLICA IDENTITY FULL;
ALTER TABLE test_cases      REPLICA IDENTITY FULL;
ALTER TABLE enrollments     REPLICA IDENTITY FULL;
ALTER TABLE lesson_progress REPLICA IDENTITY FULL;
ALTER TABLE submissions     REPLICA IDENTITY FULL;
ALTER TABLE grades          REPLICA IDENTITY FULL;

-- --- reference seed (mirrors src/edu_platform/demo/seed.py) --------------------------------
INSERT INTO organisations (organisation_id, name, plan) VALUES
  ('org-acme', 'Acme Learning', 'enterprise'),
  ('org-globex', 'Globex Academy', 'team')
ON CONFLICT DO NOTHING;

INSERT INTO courses (course_id, title, skill, level, owner_organisation_id) VALUES
  ('c-sql-101', 'SQL Foundations', 'sql', 'beginner', 'org-acme'),
  ('c-py-201', 'Python for Data', 'python', 'intermediate', 'org-acme'),
  ('c-de-301', 'Data Engineering Basics', 'data_engineering', 'intermediate', 'org-acme')
ON CONFLICT DO NOTHING;

INSERT INTO course_content (content_id, course_id, content_type, title, version, object_key, duration_sec) VALUES
  ('v-sql-select', 'c-sql-101', 'video_transcript', 'Selecting rows', 1, 'courses/c-sql-101/v-sql-select/v1.vtt', 240),
  ('v-sql-joins', 'c-sql-101', 'video_transcript', 'Joins', 1, 'courses/c-sql-101/v-sql-joins/v1.vtt', 420),
  ('v-sql-group', 'c-sql-101', 'video_transcript', 'Grouping and aggregates', 1, 'courses/c-sql-101/v-sql-group/v1.vtt', 360),
  ('v-py-func', 'c-py-201', 'video_transcript', 'Functions', 1, 'courses/c-py-201/v-py-func/v1.vtt', 300),
  ('v-py-lists', 'c-py-201', 'video_transcript', 'Lists and loops', 1, 'courses/c-py-201/v-py-lists/v1.vtt', 330),
  ('v-py-files', 'c-py-201', 'video_transcript', 'Working with files', 1, 'courses/c-py-201/v-py-files/v1.vtt', 280),
  ('v-de-batch', 'c-de-301', 'video_transcript', 'Batch versus streaming', 1, 'courses/c-de-301/v-de-batch/v1.vtt', 500),
  ('v-de-medallion', 'c-de-301', 'video_transcript', 'Medallion architecture', 1, 'courses/c-de-301/v-de-medallion/v1.vtt', 450)
ON CONFLICT DO NOTHING;

INSERT INTO lessons (lesson_id, course_id, content_id, title, ordinal) VALUES
  ('l-sql-1', 'c-sql-101', 'v-sql-select', 'Selecting rows', 1),
  ('l-sql-2', 'c-sql-101', 'v-sql-joins', 'Joins', 2),
  ('l-sql-3', 'c-sql-101', 'v-sql-group', 'Grouping and aggregates', 3),
  ('l-py-1', 'c-py-201', 'v-py-func', 'Functions', 1),
  ('l-py-2', 'c-py-201', 'v-py-lists', 'Lists and loops', 2),
  ('l-py-3', 'c-py-201', 'v-py-files', 'Working with files', 3),
  ('l-de-1', 'c-de-301', 'v-de-batch', 'Batch versus streaming', 1),
  ('l-de-2', 'c-de-301', 'v-de-medallion', 'Medallion architecture', 2)
ON CONFLICT DO NOTHING;

INSERT INTO assignments (assignment_id, course_id, title, language, due_at) VALUES
  ('a-py-fizz', 'c-py-201', 'FizzBuzz', 'python', now() + interval '7 days'),
  ('a-py-even', 'c-py-201', 'Sum of even numbers', 'python', now() + interval '10 days'),
  ('a-sql-joins', 'c-sql-101', 'Students with two or more courses', 'sql', now() + interval '5 days')
ON CONFLICT DO NOTHING;

INSERT INTO test_cases (assignment_id, test_case_id, name, is_hidden) VALUES
  ('a-py-fizz', 't1_small', 'small', false), ('a-py-fizz', 't2_fizzbuzz', 'fizzbuzz', false),
  ('a-py-fizz', 't3_empty', 'empty', false), ('a-py-fizz', 't4_fizz', 'fizz', true),
  ('a-py-fizz', 't5_buzz', 'buzz', true),
  ('a-py-even', 't1_mixed', 'mixed', false), ('a-py-even', 't2_empty', 'empty', false),
  ('a-py-even', 't3_negative', 'negative', false), ('a-py-even', 't4_zero', 'zero', true),
  ('a-py-even', 't5_pairs', 'pairs', true),
  ('a-sql-joins', 't1_base', 'base', false), ('a-sql-joins', 't2_no_courses', 'no courses', false),
  ('a-sql-joins', 't3_ties', 'ties', false)
ON CONFLICT DO NOTHING;

INSERT INTO learners (learner_id, organisation_id, advisor_id, email, full_name, country_code) VALUES
  ('l-001', 'org-acme', 'adv-1', 'an.pham@example.edu', 'An Pham', 'VN'),
  ('l-002', 'org-acme', 'adv-1', 'binh.le@example.edu', 'Binh Le', 'VN'),
  ('l-003', 'org-acme', 'adv-1', 'chi.hoang@example.edu', 'Chi Hoang', 'VN'),
  ('l-004', 'org-acme', 'adv-1', 'dung.vo@example.edu', 'Dung Vo', 'VN'),
  ('l-005', 'org-acme', 'adv-1', 'ha.dang@example.edu', 'Ha Dang', 'VN'),
  ('l-006', 'org-acme', 'adv-1', 'khoa.bui@example.edu', 'Khoa Bui', 'VN'),
  ('l-007', 'org-globex', 'adv-2', 'lan.do@example.edu', 'Lan Do', 'VN'),
  ('l-008', 'org-globex', 'adv-2', 'minh.ngo@example.edu', 'Minh Ngo', 'VN'),
  ('l-009', 'org-globex', 'adv-2', 'nam.truong@example.edu', 'Nam Truong', 'VN')
ON CONFLICT DO NOTHING;

INSERT INTO enrollments (enrollment_id, learner_id, course_id, organisation_id, status)
SELECT 'e-' || l.learner_id || '-' || c.course_id, l.learner_id, c.course_id, l.organisation_id, 'active'
FROM learners l
JOIN (VALUES ('l-001','c-sql-101'),('l-001','c-py-201'),('l-002','c-sql-101'),('l-002','c-py-201'),
             ('l-003','c-sql-101'),('l-003','c-py-201'),('l-003','c-de-301'),('l-004','c-sql-101'),
             ('l-004','c-py-201'),('l-005','c-sql-101'),('l-005','c-py-201'),('l-005','c-de-301'),
             ('l-006','c-sql-101'),('l-007','c-sql-101'),('l-007','c-py-201'),('l-008','c-py-201'),
             ('l-009','c-sql-101')) AS c(learner_id, course_id)
  ON c.learner_id = l.learner_id
ON CONFLICT DO NOTHING;
