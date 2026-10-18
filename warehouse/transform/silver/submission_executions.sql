-- silver.submission_executions <- bronze.domain_events (topic grading.sandbox_result.raw.v1).
-- A sandbox run is immutable: insert-only on (submission_id, worker_run_id). stdout/stderr
-- text stays in bronze; silver keeps the structured outcome (contract: schemas/grading/v1).
MERGE INTO silver.submission_executions AS t
USING (
  SELECT e.submission_id, e.worker_run_id, e.exit_code, e.exec_time_ms, e.max_rss_kb,
         coalesce(e.timed_out, false) AS timed_out,
         length(coalesce(e.stderr, '')) > 0 AS has_stderr,
         CASE WHEN e.assertions IS NULL THEN 0 ELSE size(e.assertions) END AS tests_total,
         CASE WHEN e.assertions IS NULL THEN 0
              ELSE size(filter(e.assertions, a -> a.status = 'passed')) END AS tests_passed,
         kafka_timestamp AS executed_at, ingest_date AS _ingest_date
  FROM (
    SELECT from_json(payload, 'submission_id STRING, worker_run_id STRING, stderr STRING, exit_code INT, exec_time_ms BIGINT, max_rss_kb BIGINT, timed_out BOOLEAN, assertions ARRAY<STRUCT<test_case_id: STRING, status: STRING, duration_ms: BIGINT>>') AS e,
           kafka_timestamp, ingest_date,
           row_number() OVER (PARTITION BY get_json_object(payload, '$.submission_id'), get_json_object(payload, '$.worker_run_id')
                              ORDER BY kafka_offset DESC) AS rn
    FROM _src
  ) WHERE rn = 1 AND e.submission_id IS NOT NULL AND e.worker_run_id IS NOT NULL
) AS s
ON t.submission_id = s.submission_id AND t.worker_run_id = s.worker_run_id
WHEN NOT MATCHED THEN INSERT
  (submission_id, worker_run_id, exit_code, exec_time_ms, max_rss_kb, timed_out, has_stderr,
   tests_total, tests_passed, executed_at, _ingest_date, _processed_at)
  VALUES (s.submission_id, s.worker_run_id, s.exit_code, s.exec_time_ms, s.max_rss_kb, s.timed_out,
          s.has_stderr, s.tests_total, s.tests_passed, s.executed_at, s._ingest_date, current_timestamp());
