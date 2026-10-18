-- GOLD DIMENSIONS (Kimball, conformed across every fact).
--
-- Surrogate keys are deterministic: xxhash64 of the natural key (SCD1) or of
-- (natural key, valid_from) (SCD2). A rebuild therefore reproduces the same keys, facts and
-- dimensions can be built independently, and no sequence/identity service is needed.
--
-- Late-arriving dimensions: a fact may reference a natural key whose source row has not
-- arrived yet (telemetry outruns CDC). The dimension build inserts an *inferred member*
-- (is_inferred = true, attributes NULL) with the same key the real row will get; when the
-- source row lands, the inferred row is overwritten in place, so facts never need re-keying.
-- Key -1 is the "not applicable / unknown" member (e.g. content of a logged_in event).

CREATE TABLE IF NOT EXISTS gold.dim_date (
  date_key     INT     NOT NULL COMMENT 'yyyymmdd',
  date         DATE    NOT NULL,
  day_of_week  INT     NOT NULL COMMENT '1 = Monday',
  day_name     STRING  NOT NULL,
  is_weekend   BOOLEAN NOT NULL,
  week_start   DATE    NOT NULL COMMENT 'Monday of the ISO week (BR8 weekly windows)',
  iso_week     INT     NOT NULL,
  month        INT     NOT NULL,
  month_name   STRING  NOT NULL,
  quarter      INT     NOT NULL,
  year         INT     NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/dim_date'
COMMENT 'Calendar dimension, generated (no source).';

CREATE TABLE IF NOT EXISTS gold.dim_activity (
  activity_key         BIGINT NOT NULL,
  verb                 STRING NOT NULL,
  activity_group       STRING NOT NULL COMMENT 'access | content | assessment | social',
  engagement_category  STRING COMMENT 'login | view | attempt | discussion (EngagementPolicy weights); NULL = not scored',
  video_interaction    STRING COMMENT 'play | pause | seek (BR7 heatmap); NULL = not a video control',
  description          STRING
) USING DELTA
LOCATION '${lakehouse_root}/gold/dim_activity'
COMMENT 'Learning-verb vocabulary. Static, kept in sync with the telemetry and analytics domain by a unit test.';

CREATE TABLE IF NOT EXISTS gold.dim_organisation (
  organisation_key   BIGINT  NOT NULL,
  organisation_id    STRING  NOT NULL,
  organisation_name  STRING,
  plan               STRING,
  is_inferred        BOOLEAN NOT NULL,
  _built_at          TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/dim_organisation'
COMMENT 'SCD1. B2B customer organisations (BR6).';

CREATE TABLE IF NOT EXISTS gold.dim_learner (
  learner_key        BIGINT    NOT NULL COMMENT 'xxhash64(learner_pseudonym, valid_from)',
  learner_pseudonym  STRING    NOT NULL COMMENT 'Durable key; HMAC pseudonym, never the raw id',
  organisation_id    STRING,
  advisor_id         STRING,
  country_code       STRING,
  signed_up_date     DATE,
  attr_hash          BIGINT    COMMENT 'Hash of tracked attributes; a change opens a new version',
  valid_from         TIMESTAMP NOT NULL COMMENT 'First version starts at 1900-01-01',
  valid_to           TIMESTAMP NOT NULL COMMENT 'Open version ends at 9999-12-31',
  is_current         BOOLEAN   NOT NULL,
  is_inferred        BOOLEAN   NOT NULL,
  _built_at          TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/dim_learner'
COMMENT 'SCD2 on organisation_id / advisor_id / country: B2B history is attributed to the org at the time.';

CREATE TABLE IF NOT EXISTS gold.dim_course (
  course_key             BIGINT  NOT NULL,
  course_id              STRING  NOT NULL,
  course_title           STRING,
  skill                  STRING,
  level                  STRING,
  owner_organisation_id  STRING,
  lesson_count           INT     COMMENT 'Active lessons; denominator of completion rates',
  is_inferred            BOOLEAN NOT NULL,
  _built_at              TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/dim_course'
COMMENT 'SCD1.';

CREATE TABLE IF NOT EXISTS gold.dim_lesson (
  lesson_key    BIGINT  NOT NULL,
  lesson_id     STRING  NOT NULL,
  course_id     STRING,
  course_key    BIGINT,
  lesson_title  STRING,
  ordinal       INT,
  content_id    STRING,
  is_inferred   BOOLEAN NOT NULL,
  _built_at     TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/dim_lesson'
COMMENT 'SCD1.';

CREATE TABLE IF NOT EXISTS gold.dim_content (
  content_key    BIGINT    NOT NULL COMMENT 'xxhash64(content_id, valid_from)',
  content_id     STRING    NOT NULL,
  version        INT       COMMENT 'Source content version; NULL for an inferred member',
  course_id      STRING,
  content_type   STRING,
  content_title  STRING,
  duration_sec   INT,
  object_key     STRING,
  valid_from     TIMESTAMP NOT NULL,
  valid_to       TIMESTAMP NOT NULL,
  is_current     BOOLEAN   NOT NULL,
  is_inferred    BOOLEAN   NOT NULL,
  _built_at      TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/dim_content'
COMMENT 'SCD2 by content version: a re-cut video shifts its seconds, so BR7 heatmaps are per version.';

CREATE TABLE IF NOT EXISTS gold.dim_assignment (
  assignment_key    BIGINT  NOT NULL,
  assignment_id     STRING  NOT NULL,
  course_id         STRING,
  course_key        BIGINT,
  lesson_id         STRING,
  assignment_title  STRING,
  language          STRING,
  due_at            TIMESTAMP,
  max_score         DOUBLE,
  test_case_count   INT,
  is_inferred       BOOLEAN NOT NULL,
  _built_at         TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/dim_assignment'
COMMENT 'SCD1.';

CREATE TABLE IF NOT EXISTS gold.dim_test_case (
  test_case_key   BIGINT  NOT NULL COMMENT 'xxhash64(assignment_id, test_case_id)',
  assignment_id   STRING  NOT NULL,
  test_case_id    STRING  NOT NULL,
  assignment_key  BIGINT,
  test_case_name  STRING,
  weight          DOUBLE,
  is_hidden       BOOLEAN,
  is_inferred     BOOLEAN NOT NULL,
  _built_at       TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/gold/dim_test_case'
COMMENT 'SCD1. Grain of the BR4 anomaly analysis.';
