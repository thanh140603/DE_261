"""BR4 typed Spark SQL. Shared snapshot inputs, no PostgreSQL joins or Python UDFs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

SCHEMAS = {
    "courses": "id STRING,title STRING,telemetry_enabled BOOLEAN,created_at TIMESTAMP",
    "assignments": (
        "id STRING,course_id STRING,title STRING,deadline TIMESTAMP,requir"
        "ed BOOLEAN,published_at TIMESTAMP"
    ),
    "questions": "id STRING,version INT,assignment_id STRING,title STRING,created_at TIMESTAMP",
    "test_cases": (
        "id STRING,version INT,question_id STRING,question_version INT,req"
        "uired BOOLEAN,created_at TIMESTAMP"
    ),
    "submissions": (
        "id STRING,student_id STRING,course_id STRING,assignment_id STRING"
        ",question_id STRING,question_version INT,submitted_at TIMESTAMP,e"
        "xecution_status STRING"
    ),
    "evaluations": (
        "id STRING,submission_id STRING,test_case_id STRING,test_case_vers"
        "ion INT,status STRING,is_valid_evaluation BOOLEAN,evaluated_at TI"
        "MESTAMP"
    ),
    "enrollments": (
        "id STRING,student_id STRING,course_id STRING,status STRING,enrolled_at TIMESTAMP"
    ),
    "activity_events": (
        "id STRING,student_id STRING,course_id STRING,event_type STRING,event_time TIMESTAMP"
    ),
    "clocks": "id STRING,evaluated_at TIMESTAMP",
}

FACT_SQL = """
WITH base AS (
 SELECT s.*,q.title question_title,a.title assignment_title
 FROM src_submissions s JOIN src_questions q ON q.id=s.question_id AND q.version=s.question_version
 JOIN src_assignments a ON a.id=s.assignment_id AND q.assignment_id=a.id AND a.course_id=s.course_id
 WHERE s.submitted_at >= :start AND s.submitted_at < :end AND (:course IS NULL OR
s.course_id=:course)
), versions AS (
 SELECT s.id submission_id,t.*,row_number() OVER(PARTITION BY s.id,t.id ORDER BY t.version DESC) rn
 FROM base s JOIN src_test_cases t ON t.question_id=s.question_id
 AND t.question_version=s.question_version AND t.created_at <= s.submitted_at
), manifest AS (SELECT * FROM versions WHERE rn=1 AND required)
SELECT s.id submission_id,s.student_id,s.course_id,s.assignment_id,s.question_id,s.question_version,
 s.question_title,s.assignment_title,s.submitted_at,t.id test_case_id,t.version test_case_version,
 e.status,coalesce(e.is_valid_evaluation AND e.status IN ('passed','failed','error','timeout')
 AND s.execution_status='evaluated',false) valid,
 (s.execution_status='infra_error' OR coalesce(e.status='infra_error',false)) infra_error
FROM base s LEFT JOIN manifest t ON t.submission_id=s.id
LEFT JOIN src_evaluations e ON e.submission_id=s.id AND e.test_case_id=t.id
 AND e.test_case_version=t.version AND e.evaluated_at < :end
"""

ATTEMPT_SQL = """
SELECT course_id,assignment_id,question_id,question_version,question_title,assignment_title,
 submission_id,student_id,submitted_at,
 bool_and(valid) AND count(test_case_id)>0 valid,
 coalesce(bool_and(status='passed'),false) passed,bool_or(infra_error) infra_error
FROM assessment_facts GROUP BY course_id,assignment_id,question_id,question_version,
 question_title,assignment_title,submission_id,student_id,submitted_at
"""

QUESTION_SQL = """
WITH ordered AS (
 SELECT *,row_number() OVER(PARTITION BY question_id,question_version,student_id,valid
 ORDER BY submitted_at,submission_id) first_n,
 row_number() OVER(PARTITION BY question_id,question_version,student_id,valid
 ORDER BY submitted_at DESC,submission_id DESC) last_n FROM assessment_attempts
)
SELECT course_id,assignment_id,question_id,question_version,question_title,assignment_title,
 count_if(valid) total_valid_evaluations,count_if(valid AND passed) passed_evaluations,
 count_if(valid AND NOT passed) failed_evaluations,
 count(DISTINCT CASE WHEN valid THEN student_id END) unique_students,
 count_if(NOT valid) invalid_evaluations,count_if(infra_error) infrastructure_errors,
 count_if(valid AND first_n=1) first_attempts,count_if(valid AND first_n=1 AND passed) first_passes,
 count_if(valid AND last_n=1) latest_attempts,count_if(valid AND last_n=1 AND passed) latest_passes
FROM ordered GROUP BY
course_id,assignment_id,question_id,question_version,question_title,assignment_title
"""

CASE_SQL = """
SELECT course_id,assignment_id,question_id,question_version,test_case_id,test_case_version,
 count_if(valid) total_valid_evaluations,count_if(valid AND status='passed') passed_evaluations,
 count_if(valid AND status<>'passed') failed_evaluations,
 count(DISTINCT CASE WHEN valid THEN student_id END) unique_students,
 count_if(NOT valid) invalid_evaluations,count_if(infra_error) infrastructure_errors
FROM assessment_facts WHERE test_case_id IS NOT NULL
GROUP BY course_id,assignment_id,question_id,question_version,test_case_id,test_case_version
"""


def register(spark: Any, current: Any) -> None:
    from pyspark.sql import functions as f

    for table, schema in SCHEMAS.items():
        (
            current.filter((f.col("table_name") == table) & ~f.col("deleted"))
            .select(f.from_json("data", schema).alias("r"))
            .select("r.*")
            .createOrReplaceTempView("src_" + table)
        )


def facts(spark: Any, start: datetime, end: datetime, course: str | None) -> Any:
    return spark.sql(FACT_SQL, args={"start": start, "end": end, "course": course})


def aggregate(spark: Any, frame: Any) -> tuple[Any, Any]:
    from pyspark.sql import functions as f

    frame.createOrReplaceTempView("assessment_facts")
    spark.sql(ATTEMPT_SQL).createOrReplaceTempView("assessment_attempts")

    def rates(df: Any, question: bool = False) -> Any:
        df = df.withColumn(
            "pass_rate",
            f.when(
                f.col("total_valid_evaluations") > 0,
                f.col("passed_evaluations") / f.col("total_valid_evaluations"),
            ),
        )
        if question:
            for prefix in ("first", "latest"):
                df = df.withColumn(
                    prefix + "_attempt_pass_rate",
                    f.when(
                        f.col(prefix + "_attempts") > 0,
                        f.col(prefix + "_passes") / f.col(prefix + "_attempts"),
                    ),
                )
        return df

    return rates(spark.sql(QUESTION_SQL), True), rates(spark.sql(CASE_SQL))


def cohort(spark: Any, current_facts: Any, historical_facts: Any) -> Any:
    """Prior valid performance on OTHER questions; ties at percentile 80 are retained."""
    historical_facts.createOrReplaceTempView("assessment_facts")
    spark.sql(ATTEMPT_SQL).createOrReplaceTempView("prior_attempts")
    current_facts.createOrReplaceTempView("current_facts")
    return spark.sql("""
    WITH latest AS (
      SELECT *,row_number() OVER(PARTITION BY course_id,student_id,question_id
        ORDER BY submitted_at DESC,submission_id DESC) rn FROM prior_attempts WHERE valid
    ), targets AS (SELECT DISTINCT course_id,question_id,question_version FROM current_facts),
    scores AS (
      SELECT t.course_id,t.question_id,t.question_version,p.student_id,avg(CAST(p.passed AS
DOUBLE)) ability
      FROM targets t JOIN latest p ON t.course_id=p.course_id AND t.question_id<>p.question_id
AND p.rn=1
      GROUP BY t.course_id,t.question_id,t.question_version,p.student_id HAVING count(*)>=3
    ), boundaries AS (
      SELECT course_id,question_id,question_version,percentile(ability,0.8) threshold
      FROM scores GROUP BY course_id,question_id,question_version
    ), strong AS (
      SELECT s.* FROM scores s JOIN boundaries b USING(course_id,question_id,question_version)
      WHERE s.ability>=b.threshold
    )
    SELECT c.course_id,c.question_id,c.question_version,c.test_case_id,c.test_case_version,
      count(DISTINCT CASE WHEN c.valid THEN c.student_id END) cohort_students,
      count_if(c.valid) cohort_attempts,count_if(c.valid AND c.status='passed') cohort_passes
    FROM current_facts c JOIN strong s USING(course_id,question_id,question_version,student_id)
    WHERE c.test_case_id IS NOT NULL
    GROUP BY c.course_id,c.question_id,c.question_version,c.test_case_id,c.test_case_version
    """)
