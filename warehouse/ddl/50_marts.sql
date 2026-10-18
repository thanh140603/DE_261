-- MARTS: one table per business requirement, shaped for the dashboard/API that reads it.
-- Built from gold only. Thresholds come from the analytics domain value objects
-- (AnomalyThreshold, MinCohortPolicy, EngagementWeights) and are recorded on every row so a
-- reader can tell which policy produced it.

-- BR4 (Instructor): test cases / questions with an abnormal fail rate.
CREATE TABLE IF NOT EXISTS mart.assessment_item_stats (
  as_of_date                   DATE    NOT NULL,
  window_start                 DATE    NOT NULL,
  window_end                   DATE    NOT NULL,
  course_id                    STRING,
  assignment_id                STRING  NOT NULL,
  assignment_title             STRING,
  test_case_id                 STRING  NOT NULL,
  test_case_name               STRING,
  attempts                     BIGINT  NOT NULL,
  passes                       BIGINT  NOT NULL,
  pass_rate                    DOUBLE  NOT NULL,
  assignment_median_pass_rate  DOUBLE  NOT NULL,
  is_anomalous                 BOOLEAN NOT NULL,
  policy_min_attempts          INT     NOT NULL,
  policy_max_pass_rate         DOUBLE  NOT NULL,
  policy_min_delta             DOUBLE  NOT NULL,
  _built_at                    TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (as_of_date)
LOCATION '${lakehouse_root}/mart/assessment_item_stats'
COMMENT 'BR4. Pass rate per test case over a trailing window; anomalous = far below the assignment median.';

-- BR6 (Admin / B2B): skill progress and completion per organisation, k-anonymous.
CREATE TABLE IF NOT EXISTS mart.org_progress (
  as_of_date         DATE    NOT NULL,
  organisation_id    STRING  NOT NULL,
  organisation_name  STRING,
  course_id          STRING  NOT NULL,
  course_title       STRING,
  skill              STRING,
  cohort_size        BIGINT  NOT NULL,
  completion_rate    DOUBLE  COMMENT 'NULL when suppressed (cohort_size < k)',
  avg_mastery        DOUBLE  COMMENT 'NULL when suppressed (cohort_size < k)',
  completed_learners BIGINT  COMMENT 'NULL when suppressed',
  is_suppressed      BOOLEAN NOT NULL,
  min_cohort_k       INT     NOT NULL,
  _built_at          TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (as_of_date)
LOCATION '${lakehouse_root}/mart/org_progress'
COMMENT 'BR6. The only table B2B admins can read; no learner-level rows, small cohorts suppressed.';

-- BR7 (Instructor): per-second play/pause/seek density of a lecture video.
CREATE TABLE IF NOT EXISTS mart.video_heatmap (
  as_of_date       DATE   NOT NULL,
  window_days      INT    NOT NULL,
  content_id       STRING NOT NULL,
  content_version  INT,
  content_title    STRING,
  course_id        STRING,
  duration_sec     INT,
  second           INT    NOT NULL,
  play_count       BIGINT NOT NULL,
  pause_count      BIGINT NOT NULL,
  seek_count       BIGINT NOT NULL,
  unique_learners  BIGINT NOT NULL,
  intensity        DOUBLE NOT NULL COMMENT 'interactions / max interactions of the video (0..1)',
  _built_at        TIMESTAMP NOT NULL
) USING DELTA
LOCATION '${lakehouse_root}/mart/video_heatmap'
COMMENT 'BR7. Dense grid (every second of every version) over the trailing window; replaced each run.';

-- BR8 (Instructor): weekly engagement score per learner/course and declining-trend flag.
CREATE TABLE IF NOT EXISTS mart.engagement_trend (
  as_of_date         DATE    NOT NULL,
  course_id          STRING  NOT NULL,
  learner_pseudonym  STRING  NOT NULL,
  week_index         INT     NOT NULL COMMENT '1 = oldest window, n = most recent',
  week_start         DATE    NOT NULL,
  engagement_score   DOUBLE  NOT NULL,
  delta_vs_previous  DOUBLE  COMMENT 'Negative = declining',
  is_declining       BOOLEAN NOT NULL COMMENT 'Series flag: dropped >= decline_ratio in each of the last two windows',
  course_avg_score   DOUBLE  NOT NULL,
  decline_ratio      DOUBLE  NOT NULL,
  _built_at          TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (as_of_date)
LOCATION '${lakehouse_root}/mart/engagement_trend'
COMMENT 'BR8. Weekly windows ending at as_of_date (ComputeEngagementTrend semantics).';
