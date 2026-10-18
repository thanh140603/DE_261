-- silver.test_case_results <- bronze.domain_events (topic grading.sandbox_result.raw.v1).
-- One row per assertion. expected/actual outputs are not copied (they can echo learner input).
MERGE INTO silver.test_case_results AS t
USING (
  SELECT submission_id, worker_run_id, a.test_case_id, coalesce(a.status, 'error') AS status,
         a.duration_ms, executed_at, _ingest_date
  FROM (
    SELECT e.submission_id, e.worker_run_id, kafka_timestamp AS executed_at, ingest_date AS _ingest_date,
           explode(e.assertions) AS a
    FROM (
      SELECT from_json(payload, 'submission_id STRING, worker_run_id STRING, assertions ARRAY<STRUCT<test_case_id: STRING, status: STRING, duration_ms: BIGINT>>') AS e,
             kafka_timestamp, ingest_date,
             row_number() OVER (PARTITION BY get_json_object(payload, '$.submission_id'), get_json_object(payload, '$.worker_run_id')
                                ORDER BY kafka_offset DESC) AS rn
      FROM _src
    ) WHERE rn = 1 AND e.submission_id IS NOT NULL AND e.worker_run_id IS NOT NULL
  ) WHERE a.test_case_id IS NOT NULL
) AS s
ON t.submission_id = s.submission_id AND t.worker_run_id = s.worker_run_id AND t.test_case_id = s.test_case_id
WHEN NOT MATCHED THEN INSERT
  (submission_id, worker_run_id, test_case_id, status, duration_ms, executed_at, _ingest_date, _processed_at)
  VALUES (s.submission_id, s.worker_run_id, s.test_case_id, s.status, s.duration_ms, s.executed_at,
          s._ingest_date, current_timestamp());
