CREATE SCHEMA IF NOT EXISTS br45_benchmark;
CREATE TABLE IF NOT EXISTS br45_benchmark.activity_windows (
    run_id text NOT NULL,
    engine text NOT NULL,
    student_id text NOT NULL,
    course_id text NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    activity_count bigint NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, engine, student_id, course_id, window_end)
);
