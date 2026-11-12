"""Accepted CDC -> versioned Delta snapshot -> Spark assessment -> atomic serving marts."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from . import jobs, spark_assessment
from .assessment import publish
from .config import AnalyticsSettings, settings
from .contracts import identity
from .db import connect, state

log = logging.getLogger(__name__)
ROW_SCHEMA = (
    "event_id STRING,table_name STRING,row_key STRING,lsn DECIMAL(30,0),"
    "deleted BOOLEAN,data STRING,raw_envelope STRING,sequence LONG"
)


def initialize(spark: Any, root: str) -> None:
    from delta.tables import DeltaTable

    current_path = root + "/source_rows"
    for path in (current_path, root + "/accepted_changes"):
        if not DeltaTable.isDeltaTable(spark, path):
            spark.createDataFrame([], ROW_SCHEMA).write.format("delta").save(path)


def start(spark: Any, cfg: AnalyticsSettings) -> Any:
    from pyspark.sql import functions as f

    root = cfg.lakehouse_root.rstrip("/")
    if "'" in root:
        raise ValueError("Lakehouse paths must not contain single quotes")
    initialize(spark, root)
    source = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", cfg.kafka)
        .option("subscribe", cfg.clean_topic)
        .option("startingOffsets", "earliest")
        .option("maxOffsetsPerTrigger", 10000)
        .load()
    )
    wire_schema = ROW_SCHEMA.replace("lsn DECIMAL(30,0)", "lsn STRING")
    rows = (
        source.select(f.from_json(f.col("value").cast("string"), wire_schema).alias("r"))
        .select("r.*")
        .withColumn("lsn", f.col("lsn").cast("decimal(30,0)"))
    )

    def land(batch: Any, batch_id: int) -> None:
        merged = merge_batch(spark, root, batch)
        if merged is None:
            return
        sequence, version = merged
        with connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('br45-cdc-progress'))")
            state(
                conn,
                "lakehouse_sequence",
                max(sequence, state(conn, "lakehouse_sequence") or 0),
            )
            state(
                conn,
                "lakehouse",
                {
                    "sequence": max(sequence, state(conn, "lakehouse_sequence") or 0),
                    "version": version,
                    "batch_id": batch_id,
                    "last_success_at": datetime.now(UTC).isoformat(),
                },
            )

    return (
        rows.writeStream.foreachBatch(land)
        .option("checkpointLocation", cfg.checkpoint + "-delta")
        .trigger(processingTime="10 seconds")
        .start()
    )


def merge_batch(spark: Any, root: str, batch: Any) -> tuple[int, int] | None:
    from delta.tables import DeltaTable
    from pyspark.sql import Window
    from pyspark.sql import functions as f

    if batch.isEmpty():
        return None
    current_path = root + "/source_rows"
    batch.persist()
    try:
        if (
            batch.filter(
                "event_id IS NULL OR table_name IS NULL OR row_key IS NULL "
                "OR lsn IS NULL OR sequence IS NULL"
            )
            .limit(1)
            .count()
        ):
            raise ValueError("Invalid normalized CDC envelope; refusing snapshot publication")
        (
            DeltaTable.forPath(spark, root + "/accepted_changes")
            .alias("t")
            .merge(batch.dropDuplicates(["event_id"]).alias("s"), "t.event_id=s.event_id")
            .whenNotMatchedInsertAll()
            .execute()
        )
        ordered = Window.partitionBy("table_name", "row_key").orderBy(
            f.desc("lsn"), f.desc("sequence")
        )
        latest = (
            batch.withColumn("_rn", f.row_number().over(ordered)).filter("_rn=1").drop("_rn")
        )
        (
            DeltaTable.forPath(spark, current_path)
            .alias("t")
            .merge(latest.alias("s"), "t.table_name=s.table_name AND t.row_key=s.row_key")
            .whenMatchedUpdateAll(condition="s.lsn > t.lsn")
            .whenNotMatchedInsertAll()
            .execute()
        )
        sequence = batch.agg(f.max("sequence")).first()[0]
        version = (
            DeltaTable.forPath(spark, current_path).history(1).select("version").first()[0]
        )
        return int(sequence), int(version)
    finally:
        batch.unpersist()


def process(spark: Any, cfg: AnalyticsSettings) -> bool:
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('br45-cdc-progress'))")
        landed = state(conn, "lakehouse")
        if not landed or landed["sequence"] < (state(conn, "assessment_sequence") or 0):
            return False
        job = jobs.pending(conn, "spark", landed["sequence"])
        revision = state(conn, "assessment_source_revision") or "empty"
    if job is None:
        return False
    try:
        root = cfg.lakehouse_root.rstrip("/")
        version = landed["version"]
        snapshot = (
            spark.read.format("delta").option("versionAsOf", version).load(root + "/source_rows")
        )
        spark_assessment.register(spark, snapshot)
        start_at, end_at, course = job["window_start"], job["window_end"], job["course_id"]
        frame = spark_assessment.facts(spark, start_at, end_at, course).persist()
        try:
            q, t = spark_assessment.aggregate(spark, frame)
            qs = [r.asDict() for r in q.toLocalIterator()]
            ts = [r.asDict() for r in t.toLocalIterator()]
            prior_frame = spark_assessment.facts(
                spark, start_at - (end_at - start_at), start_at, course
            )
            pq, pt = spark_assessment.aggregate(spark, prior_frame)
            previous = [r.asDict() for df in (pq, pt) for r in df.toLocalIterator()]
            history = spark_assessment.facts(
                spark, datetime(1970, 1, 1, tzinfo=UTC), start_at, course
            )
            groups = {
                tuple(
                    r[k]
                    for k in (
                        "course_id",
                        "question_id",
                        "question_version",
                        "test_case_id",
                        "test_case_version",
                    )
                ): r.asDict()
                for r in spark_assessment.cohort(spark, frame, history).toLocalIterator()
            }
            for row in ts:
                key = tuple(
                    row[k]
                    for k in (
                        "course_id",
                        "question_id",
                        "question_version",
                        "test_case_id",
                        "test_case_version",
                    )
                )
                group = groups.get(key, {})
                count = group.get("cohort_attempts", 0)
                students = group.get("cohort_students", 0)
                row.update(
                    cohort_students=students,
                    cohort_attempts=count,
                    cohort_pass_rate=group.get("cohort_passes", 0) / count
                    if count and students >= cfg.min_students
                    else None,
                    cohort_definition=(
                        "Prior other-question performance >= percentile 80; ties retained;"
                        " minimum 3 questions"
                    ),
                )
            publication = identity(job["id"], version, revision, job["lease_generation"])
            publication_path = root + "/publications/" + publication
            fact_path = publication_path + "/facts"
            frame.write.format("delta").mode("errorifexists").save(fact_path)
            for name in ("courses", "questions", "test_cases", "enrollments"):
                spark.table("src_" + name).write.format("delta").mode("errorifexists").save(
                    publication_path + "/dimensions/" + name
                )
            spark.sql(f"CREATE DATABASE IF NOT EXISTS br45_gold LOCATION '{root}/gold'")
            spark.sql(
                f"CREATE TABLE IF NOT EXISTS br45_gold.facts_{publication[:16]} "
                f"USING DELTA LOCATION '{fact_path}'"
            )
            with connect() as conn:
                if not jobs.owns_lease(conn, job):
                    return False
                qs, ts = publish(conn, qs, ts, previous, start_at, end_at, course, cfg, revision)
                jobs.complete(conn, job, revision, publication, version)
                state(
                    conn,
                    "assessment_publication",
                    {
                        "job_id": job["id"],
                        "engine": "spark",
                        "source_delta_version": version,
                        "source_revision": revision,
                        "publication_id": publication,
                        "dimensions_path": publication_path + "/dimensions",
                        "facts_path": fact_path,
                        "fact_partitions": frame.rdd.getNumPartitions(),
                        "last_success_at": datetime.now(UTC).isoformat(),
                    },
                )
        finally:
            frame.unpersist()
        return True
    except Exception as error:
        log.exception("Assessment job failed: %s", job["id"])
        with connect() as conn:
            jobs.fail(conn, job, error)
        return False


def bootstrap() -> int:
    """Publish existing accepted rows once when upgrading an existing v1 deployment."""
    from .events import enqueue

    cfg = settings()
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('br45-cdc-progress'))")
        if state(conn, "delta_bootstrap_v2"):
            return 0
        count = 0
        for row in conn.execute("SELECT * FROM analytics.clean_rows ORDER BY table_name,row_key"):
            sequence = enqueue(
                conn,
                cfg.clean_topic,
                row["table_name"] + ":" + row["row_key"],
                {
                    "event_id": identity(
                        "bootstrap-v2", row["table_name"], row["row_key"], str(row["lsn"])
                    ),
                    "table_name": row["table_name"],
                    "row_key": row["row_key"],
                    "lsn": str(row["lsn"]),
                    "deleted": row["deleted"],
                    "data": json.dumps(row["data"]),
                    "raw_envelope": None,
                },
            )
            state(conn, "clean_sequence", max(sequence, state(conn, "clean_sequence") or 0))
            count += 1
        state(conn, "delta_bootstrap_v2", True)
        state(conn, "assessment_sequence", state(conn, "clean_sequence") or 0)
        at = state(conn, "evaluation_clock")
        if at:
            from .contracts import timestamp
            from .db import clean

            for course in clean(conn, "courses"):
                jobs.request(conn, course["id"], timestamp(at) - timedelta(days=30), timestamp(at))
        return count
