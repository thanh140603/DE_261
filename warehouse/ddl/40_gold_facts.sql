-- GOLD FACTS. Every fact states its grain; keys reference the conformed dimensions in
-- 30_gold_dimensions.sql. Durable natural keys (learner_pseudonym, course_id, ...) are kept
-- next to surrogate keys where downstream feature/mart jobs join on them.
--
-- Load strategies (warehouse/models.yaml):
--   window   re-derive the date partitions of the last N days from silver (late events,
--            late dimensions) - replaces exactly those partitions, idempotent
--   full     rebuild from silver (accumulating snapshots that reflect current state)

-- Grain: one normalised learning event.  BR6 / BR7 / BR8 drill-down.
CREATE TABLE IF NOT EXISTS gold.fct_learning_event (
  event_id            STRING    NOT NULL,
  event_date          DATE      NOT NULL,
  date_key            INT       NOT NULL,
  learner_key         BIGINT    NOT NULL,
  course_key          BIGINT    NOT NULL,
  content_key         BIGINT    NOT NULL COMMENT 'Content version current at occurred_at; -1 if none',
  activity_key        BIGINT    NOT NULL,
  learner_pseudonym   STRING    NOT NULL,
  course_id           STRING    NOT NULL,
  content_id          STRING,
  verb                STRING    NOT NULL,
  session_id          STRING,
  platform            STRING,
  occurred_at         TIMESTAMP NOT NULL,
  received_at         TIMESTAMP NOT NULL,
  video_position_sec  INT,
  is_late             BOOLEAN   NOT NULL,
  lateness_sec        DOUBLE    NOT NULL,
  _built_at           TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (event_date)
LOCATION '${lakehouse_root}/gold/fct_learning_event'
COMMENT 'Transaction fact. Grain: one learning event.'
TBLPROPERTIES ('edu.zorder' = 'course_key,learner_key');

-- Grain: learner x course x day.  BR8 engagement, BR2 features, BR5 login-gap context.
CREATE TABLE IF NOT EXISTS gold.fct_learner_daily_activity (
  activity_date       DATE      NOT NULL,
  date_key            INT       NOT NULL,
  learner_key         BIGINT    NOT NULL,
  course_key          BIGINT    NOT NULL,
  learner_pseudonym   STRING    NOT NULL,
  course_id           STRING    NOT NULL,
  events              BIGINT    NOT NULL,
  sessions            BIGINT    NOT NULL,
  logins              BIGINT    NOT NULL,
  views               BIGINT    NOT NULL COMMENT 'viewed + played + completed (EngagementPolicy "view")',
  attempts            BIGINT    NOT NULL COMMENT 'attempted + submitted',
  discussions         BIGINT    NOT NULL COMMENT 'posted',
  completions         BIGINT    NOT NULL,
  video_interactions  BIGINT    NOT NULL COMMENT 'played + paused + seeked',
  distinct_contents   BIGINT    NOT NULL,
  engagement_score    DOUBLE    NOT NULL COMMENT 'Weighted by EngagementWeights (login 1, view 1, attempt 2, discussion 1.5)',
  platforms           ARRAY<STRING>,
  first_event_at      TIMESTAMP NOT NULL,
  last_event_at       TIMESTAMP NOT NULL,
  _built_at           TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (activity_date)
LOCATION '${lakehouse_root}/gold/fct_learner_daily_activity'
COMMENT 'Periodic snapshot (daily). Additive counts; engagement_score additive across days.'
TBLPROPERTIES ('edu.zorder' = 'course_id,learner_pseudonym');

-- Grain: content version x second x day.  BR7 heatmap.
CREATE TABLE IF NOT EXISTS gold.fct_video_second_activity (
  activity_date    DATE   NOT NULL,
  date_key         INT    NOT NULL,
  content_key      BIGINT NOT NULL,
  content_id       STRING NOT NULL,
  content_version  INT,
  second           INT    NOT NULL COMMENT 'Playback position bucket, clamped to duration - 1',
  play_count       BIGINT NOT NULL,
  pause_count      BIGINT NOT NULL,
  seek_count       BIGINT NOT NULL,
  unique_learners  BIGINT NOT NULL COMMENT 'Distinct within the day only - NOT additive across days',
  _built_at        TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (activity_date)
LOCATION '${lakehouse_root}/gold/fct_video_second_activity'
COMMENT 'Aggregated fact. Grain: video version x second x day. Sparse: only seconds with interactions.'
TBLPROPERTIES ('edu.zorder' = 'content_key,second');

-- Grain: one submission attempt.  BR3 feedback analytics, BR4, BR5, BR2 mastery.
CREATE TABLE IF NOT EXISTS gold.fct_submission (
  submission_id      STRING    NOT NULL,
  submitted_date     DATE      NOT NULL,
  date_key           INT       NOT NULL,
  learner_key        BIGINT    NOT NULL,
  assignment_key     BIGINT    NOT NULL,
  course_key         BIGINT    NOT NULL,
  learner_pseudonym  STRING    NOT NULL,
  assignment_id      STRING    NOT NULL,
  course_id          STRING,
  attempt_number     INT,
  is_first_attempt   BOOLEAN,
  language           STRING,
  status             STRING,
  score              DOUBLE,
  pass_rate          DOUBLE,
  is_passed          BOOLEAN   COMMENT 'All tests passed',
  tests_total        INT,
  tests_passed       INT,
  runtime_ms         BIGINT,
  memory_kb          BIGINT,
  exit_code          INT,
  timed_out          BOOLEAN,
  has_stderr         BOOLEAN,
  submitted_at       TIMESTAMP NOT NULL,
  graded_at          TIMESTAMP,
  seconds_to_grade   DOUBLE    COMMENT 'Grading latency SLA (BR3)',
  _built_at          TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (submitted_date)
LOCATION '${lakehouse_root}/gold/fct_submission'
COMMENT 'Transaction fact. Grain: one submission attempt (CDC submissions + grades + latest sandbox run).'
TBLPROPERTIES ('edu.zorder' = 'assignment_id,learner_pseudonym');

-- Grain: submission x test case (latest sandbox run).  BR4.
CREATE TABLE IF NOT EXISTS gold.fct_test_case_result (
  submission_id      STRING    NOT NULL,
  submitted_date     DATE      NOT NULL,
  date_key           INT       NOT NULL,
  test_case_key      BIGINT    NOT NULL,
  assignment_key     BIGINT    NOT NULL,
  learner_key        BIGINT    NOT NULL,
  assignment_id      STRING    NOT NULL,
  test_case_id       STRING    NOT NULL,
  learner_pseudonym  STRING    NOT NULL,
  attempt_number     INT,
  status             STRING    NOT NULL,
  is_passed          BOOLEAN   NOT NULL,
  duration_ms        BIGINT,
  executed_at        TIMESTAMP NOT NULL,
  _built_at          TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (submitted_date)
LOCATION '${lakehouse_root}/gold/fct_test_case_result'
COMMENT 'Transaction fact. Grain: one test assertion of a submission.'
TBLPROPERTIES ('edu.zorder' = 'assignment_id,test_case_id');

-- Grain: one enrollment.  BR6 completion, BR5 outcome tracking.
CREATE TABLE IF NOT EXISTS gold.fct_enrollment (
  enrollment_id            STRING    NOT NULL,
  learner_key              BIGINT    NOT NULL,
  course_key               BIGINT    NOT NULL,
  organisation_key         BIGINT    NOT NULL,
  learner_pseudonym        STRING    NOT NULL,
  course_id                STRING    NOT NULL,
  organisation_id          STRING,
  status                   STRING    NOT NULL,
  enrolled_date_key        INT,
  first_activity_date_key  INT,
  last_activity_date_key   INT,
  completed_date_key       INT,
  dropped_date_key         INT,
  enrolled_at              TIMESTAMP,
  first_activity_at        TIMESTAMP,
  last_activity_at         TIMESTAMP,
  completed_at             TIMESTAMP,
  dropped_at               TIMESTAMP,
  lessons_total            INT       NOT NULL,
  lessons_completed        INT       NOT NULL,
  progress_ratio           DOUBLE    NOT NULL COMMENT 'lessons_completed / lessons_total',
  submissions              BIGINT    NOT NULL,
  avg_pass_rate            DOUBLE    COMMENT 'Mean pass_rate of graded submissions in this course',
  days_to_complete         INT,
  _built_at                TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/fct_enrollment'
COMMENT 'Accumulating snapshot. Grain: one enrollment, milestones enrolled -> first activity -> completed / dropped.';

-- Grain: learner x lesson.  BR6 skill progress.
CREATE TABLE IF NOT EXISTS gold.fct_lesson_progress (
  learner_key        BIGINT    NOT NULL,
  lesson_key         BIGINT    NOT NULL,
  course_key         BIGINT    NOT NULL,
  learner_pseudonym  STRING    NOT NULL,
  lesson_id          STRING    NOT NULL,
  course_id          STRING,
  percent_done       INT       NOT NULL,
  is_completed       BOOLEAN   NOT NULL COMMENT 'percent_done = 100 (CDC) or a completed event (telemetry)',
  first_progress_at  TIMESTAMP,
  completed_at       TIMESTAMP,
  last_updated_at    TIMESTAMP,
  _built_at          TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/fct_lesson_progress'
COMMENT 'Accumulating snapshot. Grain: learner x lesson.';

-- Grain: learner x course x day.  BR5 trend for advisors.
CREATE TABLE IF NOT EXISTS gold.fct_risk_score_daily (
  score_date          DATE    NOT NULL,
  date_key            INT     NOT NULL,
  learner_key         BIGINT  NOT NULL,
  course_key          BIGINT  NOT NULL,
  learner_pseudonym   STRING  NOT NULL,
  course_id           STRING  NOT NULL,
  max_risk_score      DOUBLE  NOT NULL,
  last_risk_score     DOUBLE  NOT NULL,
  score_updates       BIGINT  NOT NULL,
  alerts_fired        BIGINT  NOT NULL,
  is_above_threshold  BOOLEAN NOT NULL COMMENT 'last_risk_score >= SlidingWindowPolicy.alert_threshold',
  _built_at           TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (score_date)
LOCATION '${lakehouse_root}/gold/fct_risk_score_daily'
COMMENT 'Periodic snapshot (daily) of the streaming risk score.'
TBLPROPERTIES ('edu.zorder' = 'course_id,learner_pseudonym');

-- Grain: one dropout alert.  BR5 alert effectiveness.
CREATE TABLE IF NOT EXISTS gold.fct_dropout_alert (
  alert_id            STRING    NOT NULL,
  alert_date          DATE      NOT NULL,
  date_key            INT       NOT NULL,
  learner_key         BIGINT    NOT NULL,
  course_key          BIGINT    NOT NULL,
  learner_pseudonym   STRING    NOT NULL,
  course_id           STRING    NOT NULL,
  risk_score          DOUBLE    NOT NULL,
  top_signals         ARRAY<STRING>,
  alerted_at          TIMESTAMP NOT NULL,
  dropped_within_30d  BOOLEAN   COMMENT 'Outcome label: enrollment dropped within 30 days (alert precision)',
  active_after_alert  BOOLEAN   COMMENT 'Any learning activity in the 7 days after the alert',
  _built_at           TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/fct_dropout_alert'
COMMENT 'Transaction fact with outcome labels.';

-- Grain: one notification outcome per channel.  BR1 delivery analytics.
CREATE TABLE IF NOT EXISTS gold.fct_notification (
  event_id         STRING    NOT NULL,
  event_date       DATE      NOT NULL,
  date_key         INT       NOT NULL,
  learner_key      BIGINT    NOT NULL,
  notification_id  STRING    NOT NULL,
  channel          STRING,
  outcome          STRING    NOT NULL,
  reason           STRING,
  occurred_at      TIMESTAMP NOT NULL,
  _built_at        TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (event_date)
LOCATION '${lakehouse_root}/gold/fct_notification'
COMMENT 'Transaction fact. Grain: one notification outcome.';

-- Grain: one content version.  BR8 cache / search-index sync SLA.
CREATE TABLE IF NOT EXISTS gold.fct_content_sync (
  content_key       BIGINT    NOT NULL,
  content_id        STRING    NOT NULL,
  version           INT       NOT NULL,
  course_key        BIGINT    NOT NULL,
  published_at      TIMESTAMP,
  indexed_at        TIMESTAMP,
  chunk_count       INT,
  seconds_to_index  DOUBLE,
  is_indexed        BOOLEAN   NOT NULL,
  _built_at         TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/fct_content_sync'
COMMENT 'Accumulating snapshot. Grain: one content version, published -> indexed.';
