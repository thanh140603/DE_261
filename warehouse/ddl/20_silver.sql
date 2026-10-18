-- SILVER: cleaned, conformed and pseudonymised. Written only by Spark (transform/silver/*),
-- idempotently (MERGE on business keys), so the streaming micro-batch path and the batch
-- backfill path converge on the same rows. Change Data Feed is on for every table so
-- consumers (gold builds, Trino table_changes) can read increments.
--
-- Pseudonymisation (ADR 0007): learner ids become `learner_pseudonym` = HMAC-SHA256 with a
-- versioned key, identical across telemetry, CDC and domain events so joins still work.
-- Direct identifiers (email, full_name, ip, device id) are dropped, never hashed.
--
-- CDC entity tables share the columns: is_deleted (Debezium delete = soft delete),
-- _source_lsn (last applied WAL position; older changes never overwrite newer ones),
-- _source_ts (OLTP commit time), _processed_at (silver write time).

-- ---------------------------------------------------------------------------------------
-- Telemetry (BR6 normalisation; feeds BR2, BR5, BR7, BR8)
-- ---------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.learning_events (
  event_id            STRING    NOT NULL,
  learner_pseudonym   STRING    NOT NULL,
  course_id           STRING    NOT NULL,
  content_id          STRING,
  session_id          STRING    NOT NULL,
  verb                STRING    NOT NULL COMMENT 'Closed vocabulary (telemetry.domain.Verb)',
  platform            STRING    NOT NULL COMMENT 'web | android | ios',
  occurred_at         TIMESTAMP NOT NULL COMMENT 'Device event time',
  received_at         TIMESTAMP NOT NULL COMMENT 'Ingestion time',
  event_date          DATE      NOT NULL COMMENT 'Partition: date of occurred_at (event time, UTC)',
  video_position_sec  INT,
  is_late             BOOLEAN   NOT NULL COMMENT 'received_at - occurred_at beyond LatenessPolicy (5 min)',
  lateness_sec        DOUBLE    NOT NULL,
  schema_version      STRING    NOT NULL COMMENT 'Always the current version after migration',
  extensions          STRING    COMMENT 'JSON of non-first-class xAPI extensions',
  _ingest_date        DATE      NOT NULL COMMENT 'bronze partition the row came from',
  _processed_at       TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (event_date)
LOCATION '${lakehouse_root}/silver/learning_events'
COMMENT 'Normalised learning statements (NormalizeEvents use case). Unique on event_id.'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'pseudonymised', 'edu.owner' = 'telemetry',
               'edu.zorder' = 'learner_pseudonym,course_id');

-- ---------------------------------------------------------------------------------------
-- LMS reference data via CDC (sources of the conformed dimensions)
-- ---------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.organisations (
  organisation_id  STRING NOT NULL,
  name             STRING,
  plan             STRING COMMENT 'B2B plan / tier',
  updated_at       TIMESTAMP,
  is_deleted       BOOLEAN NOT NULL,
  _source_lsn      BIGINT NOT NULL,
  _source_ts       TIMESTAMP,
  _processed_at    TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/organisations'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'none', 'edu.owner' = 'platform');

CREATE TABLE IF NOT EXISTS silver.learners (
  learner_pseudonym  STRING NOT NULL,
  organisation_id    STRING,
  advisor_id         STRING COMMENT 'Staff id of the assigned academic advisor',
  country_code       STRING,
  signed_up_at       TIMESTAMP,
  updated_at         TIMESTAMP COMMENT 'OLTP updated_at - effective date of SCD2 versions',
  is_deleted         BOOLEAN NOT NULL,
  _source_lsn        BIGINT NOT NULL,
  _source_ts         TIMESTAMP,
  _processed_at      TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/learners'
COMMENT 'Learner profile without direct identifiers (email, full_name dropped by PiiPolicy).'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'pseudonymised', 'edu.owner' = 'platform');

CREATE TABLE IF NOT EXISTS silver.courses (
  course_id              STRING NOT NULL,
  title                  STRING,
  skill                  STRING COMMENT 'Skill taxonomy node used by BR6 reports and BR2 mastery',
  level                  STRING,
  owner_organisation_id  STRING,
  updated_at             TIMESTAMP,
  is_deleted             BOOLEAN NOT NULL,
  _source_lsn            BIGINT NOT NULL,
  _source_ts             TIMESTAMP,
  _processed_at          TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/courses'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'none', 'edu.owner' = 'platform');

CREATE TABLE IF NOT EXISTS silver.lessons (
  lesson_id      STRING NOT NULL,
  course_id      STRING,
  content_id     STRING COMMENT 'Primary content item (video / slides) of the lesson',
  title          STRING,
  ordinal        INT,
  updated_at     TIMESTAMP,
  is_deleted     BOOLEAN NOT NULL,
  _source_lsn    BIGINT NOT NULL,
  _source_ts     TIMESTAMP,
  _processed_at  TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/lessons'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'none', 'edu.owner' = 'platform');

CREATE TABLE IF NOT EXISTS silver.content_versions (
  content_id       STRING NOT NULL,
  version          INT    NOT NULL,
  course_id        STRING,
  content_type     STRING COMMENT 'video_transcript | slide_pdf | exercise',
  title            STRING,
  object_key       STRING COMMENT 'Object-storage key of this version',
  duration_sec     INT    COMMENT 'Video length; NULL for non-video content',
  published_at     TIMESTAMP NOT NULL COMMENT 'First time this version was seen (SCD2 effective date)',
  last_changed_at  TIMESTAMP,
  is_deleted       BOOLEAN NOT NULL,
  _source_lsn      BIGINT NOT NULL,
  _processed_at    TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/content_versions'
COMMENT 'One row per (content_id, version) from course_content CDC - full version history, not just current.'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'none', 'edu.owner' = 'content');

CREATE TABLE IF NOT EXISTS silver.assignments (
  assignment_id  STRING NOT NULL,
  course_id      STRING,
  lesson_id      STRING,
  title          STRING,
  language       STRING COMMENT 'python | sql | java | javascript',
  due_at         TIMESTAMP,
  max_score      DOUBLE,
  updated_at     TIMESTAMP,
  is_deleted     BOOLEAN NOT NULL,
  _source_lsn    BIGINT NOT NULL,
  _source_ts     TIMESTAMP,
  _processed_at  TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/assignments'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'none', 'edu.owner' = 'grading');

CREATE TABLE IF NOT EXISTS silver.test_cases (
  assignment_id  STRING NOT NULL,
  test_case_id   STRING NOT NULL COMMENT 'Unique within an assignment only',
  name           STRING,
  weight         DOUBLE,
  is_hidden      BOOLEAN,
  updated_at     TIMESTAMP,
  is_deleted     BOOLEAN NOT NULL,
  _source_lsn    BIGINT NOT NULL,
  _source_ts     TIMESTAMP,
  _processed_at  TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/test_cases'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'none', 'edu.owner' = 'grading');

-- ---------------------------------------------------------------------------------------
-- LMS transactional state via CDC
-- ---------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.enrollments (
  enrollment_id      STRING NOT NULL,
  learner_pseudonym  STRING NOT NULL,
  course_id          STRING NOT NULL,
  organisation_id    STRING COMMENT 'B2B organisation that owns the seat (NULL for B2C)',
  status             STRING NOT NULL COMMENT 'active | completed | dropped',
  enrolled_at        TIMESTAMP,
  completed_at       TIMESTAMP COMMENT 'Milestone: first time status=completed was observed',
  dropped_at         TIMESTAMP COMMENT 'Milestone: first time status=dropped was observed',
  updated_at         TIMESTAMP,
  is_deleted         BOOLEAN NOT NULL,
  _source_lsn        BIGINT NOT NULL,
  _source_ts         TIMESTAMP,
  _processed_at      TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/enrollments'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'pseudonymised', 'edu.owner' = 'platform');

CREATE TABLE IF NOT EXISTS silver.lesson_progress (
  learner_pseudonym  STRING NOT NULL,
  lesson_id          STRING NOT NULL,
  course_id          STRING,
  percent_done       INT    NOT NULL,
  first_progress_at  TIMESTAMP COMMENT 'Milestone: first change observed for this learner/lesson',
  completed_at       TIMESTAMP COMMENT 'Milestone: first time percent_done reached 100',
  updated_at         TIMESTAMP,
  is_deleted         BOOLEAN NOT NULL,
  _source_lsn        BIGINT NOT NULL,
  _source_ts         TIMESTAMP,
  _processed_at      TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/lesson_progress'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'pseudonymised', 'edu.owner' = 'platform');

CREATE TABLE IF NOT EXISTS silver.submissions (
  submission_id      STRING NOT NULL,
  learner_pseudonym  STRING NOT NULL,
  assignment_id      STRING NOT NULL,
  attempt_number     INT,
  language           STRING,
  status             STRING COMMENT 'queued | running | graded | failed | missed',
  code_ref           STRING COMMENT 'Object-storage key of the code, never the code itself',
  submitted_at       TIMESTAMP NOT NULL,
  updated_at         TIMESTAMP,
  is_deleted         BOOLEAN NOT NULL,
  _source_lsn        BIGINT NOT NULL,
  _source_ts         TIMESTAMP,
  _processed_at      TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/submissions'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'pseudonymised', 'edu.owner' = 'grading');

CREATE TABLE IF NOT EXISTS silver.grades (
  submission_id  STRING NOT NULL,
  score          DOUBLE,
  pass_rate      DOUBLE,
  graded_at      TIMESTAMP,
  is_deleted     BOOLEAN NOT NULL,
  _source_lsn    BIGINT NOT NULL,
  _source_ts     TIMESTAMP,
  _processed_at  TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/grades'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'none', 'edu.owner' = 'grading');

-- ---------------------------------------------------------------------------------------
-- Domain events (Kafka) parsed into typed tables
-- ---------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.submission_executions (
  submission_id  STRING NOT NULL,
  worker_run_id  STRING NOT NULL COMMENT 'Sandbox run; re-runs of a submission get a new id',
  exit_code      INT,
  exec_time_ms   BIGINT,
  max_rss_kb     BIGINT,
  timed_out      BOOLEAN,
  has_stderr     BOOLEAN COMMENT 'stderr text itself stays in bronze / grading service',
  tests_total    INT,
  tests_passed   INT,
  executed_at    TIMESTAMP NOT NULL,
  _ingest_date   DATE NOT NULL,
  _processed_at  TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/submission_executions'
COMMENT 'Normalised sandbox execution summary (grading.sandbox_result.raw.v1).'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'none', 'edu.owner' = 'grading');

CREATE TABLE IF NOT EXISTS silver.test_case_results (
  submission_id  STRING NOT NULL,
  worker_run_id  STRING NOT NULL,
  test_case_id   STRING NOT NULL,
  status         STRING NOT NULL COMMENT 'passed | failed | error | timeout',
  duration_ms    BIGINT,
  executed_at    TIMESTAMP NOT NULL,
  _ingest_date   DATE NOT NULL,
  _processed_at  TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/test_case_results'
COMMENT 'One row per test assertion of a sandbox run (BR4 source).'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'none', 'edu.owner' = 'grading');

CREATE TABLE IF NOT EXISTS silver.risk_scores (
  score_event_id     STRING NOT NULL,
  learner_pseudonym  STRING NOT NULL,
  course_id          STRING NOT NULL,
  risk_score         DOUBLE NOT NULL,
  computed_at        TIMESTAMP NOT NULL,
  score_date         DATE NOT NULL,
  _ingest_date       DATE NOT NULL,
  _processed_at      TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (score_date)
LOCATION '${lakehouse_root}/silver/risk_scores'
COMMENT 'Every score emitted by the Flink sliding-window job (risk.learner_score.v1).'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'pseudonymised', 'edu.owner' = 'risk',
               'edu.zorder' = 'learner_pseudonym,course_id');

CREATE TABLE IF NOT EXISTS silver.dropout_alerts (
  alert_id           STRING NOT NULL,
  learner_pseudonym  STRING NOT NULL,
  course_id          STRING NOT NULL,
  risk_score         DOUBLE NOT NULL,
  top_signals        ARRAY<STRING>,
  alerted_at         TIMESTAMP NOT NULL,
  _ingest_date       DATE NOT NULL,
  _processed_at      TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/dropout_alerts'
COMMENT 'DropoutRiskDetected events (risk.dropout_alert.v1).'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'pseudonymised', 'edu.owner' = 'risk');

CREATE TABLE IF NOT EXISTS silver.notifications (
  event_id             STRING NOT NULL,
  notification_id      STRING NOT NULL,
  recipient_pseudonym  STRING NOT NULL,
  channel              STRING COMMENT 'push | in_app | email',
  outcome              STRING NOT NULL COMMENT 'dispatched | suppressed',
  reason               STRING COMMENT 'Suppression reason (duplicate, rate_limited, ...)',
  occurred_at          TIMESTAMP NOT NULL,
  event_date           DATE NOT NULL,
  _ingest_date         DATE NOT NULL,
  _processed_at        TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (event_date)
LOCATION '${lakehouse_root}/silver/notifications'
COMMENT 'Notification outcomes (notification.dispatched.v1, notification.suppressed.v1).'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'pseudonymised', 'edu.owner' = 'notification');

CREATE TABLE IF NOT EXISTS silver.content_sync_events (
  event_id       STRING NOT NULL,
  event_type     STRING NOT NULL COMMENT 'content.version_published.v1 | content.indexed.v1',
  content_id     STRING NOT NULL,
  version        INT    NOT NULL,
  course_id      STRING,
  chunk_count    INT,
  occurred_at    TIMESTAMP NOT NULL,
  _ingest_date   DATE NOT NULL,
  _processed_at  TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/content_sync_events'
COMMENT 'Content publish / index lifecycle (content.updated.v1, content.indexed.v1) - BR8 sync SLA.'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'none', 'edu.owner' = 'content');

CREATE TABLE IF NOT EXISTS silver.content_chunks (
  chunk_id         STRING NOT NULL,
  content_id       STRING NOT NULL,
  version          INT    NOT NULL,
  ordinal          INT    NOT NULL,
  section_path     ARRAY<STRING>,
  text             STRING,
  token_count      INT,
  start_offset     INT,
  end_offset       INT,
  embedding_ref    STRING COMMENT 'Vector index document id (OpenSearch), never the raw vector',
  embedding_model  STRING,
  chunked_at       TIMESTAMP NOT NULL,
  _processed_at    TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/silver/content_chunks'
COMMENT 'Semantic chunks per content version (content_chunking_embedding_job).'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'edu.pii' = 'none', 'edu.owner' = 'content');
