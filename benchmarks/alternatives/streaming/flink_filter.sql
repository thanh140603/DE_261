SET 'execution.runtime-mode' = 'streaming';
SET 'execution.checkpointing.interval' = '1 h';
SET 'state.checkpoints.dir' = 'file:///tmp/flink-checkpoints';
SET 'pipeline.name' = 'bench-flink-filter';

CREATE TABLE events (
  event_id STRING,
  learner_pseudonym STRING,
  course_id STRING,
  event_type STRING,
  verb STRING,
  occurred_at STRING,
  session_id STRING,
  platform STRING,
  duration_ms INT,
  score DOUBLE,
  progress DOUBLE,
  ingest_time BIGINT
) WITH (
  'connector' = 'kafka',
  'topic' = 'bench.events3',
  'properties.bootstrap.servers' = 'kafka:29092',
  'properties.group.id' = 'bench-flink-filter',
  'scan.startup.mode' = 'earliest-offset',
  'format' = 'json',
  'json.fail-on-missing-field' = 'false',
  'json.ignore-parse-errors' = 'true'
);

CREATE TABLE sink (
  event_id STRING,
  learner_pseudonym STRING,
  score DOUBLE,
  ingest_time BIGINT
) WITH (
  'connector' = 'kafka',
  'topic' = 'bench.flink.out3',
  'properties.bootstrap.servers' = 'kafka:29092',
  'format' = 'json'
);

INSERT INTO sink
SELECT event_id, learner_pseudonym, score, ingest_time
FROM events
WHERE score > 0.5;
