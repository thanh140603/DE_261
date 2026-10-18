-- OFFLINE FEATURE STORE (BR2 batch branch). Registry: schemas/features/v1/feature_groups.yaml.
-- One partition per as_of_date gives point-in-time correct training sets; the latest partition
-- is materialised to Redis (online store) by batch_features_job. The streaming branch
-- (learner_session, freshness 30 s) is written to Redis by Flink and is not stored here.

CREATE TABLE IF NOT EXISTS features.learner_longterm (
  as_of_date           DATE      NOT NULL,
  learner_pseudonym    STRING    NOT NULL,
  completion_rate_30d  DOUBLE    NOT NULL,
  avg_pass_rate_30d    DOUBLE    NOT NULL,
  active_days_30d      INT       NOT NULL,
  preferred_platform   STRING,
  skill_mastery        MAP<STRING, DOUBLE>,
  feature_version      INT       NOT NULL COMMENT 'Feature group version in the registry',
  computed_at          TIMESTAMP NOT NULL
) USING DELTA
PARTITIONED BY (as_of_date)
LOCATION '${lakehouse_root}/features/learner_longterm'
COMMENT 'Feature group learner_longterm v1 (ComputeBatchFeatures semantics), freshness SLA 24 h.';
