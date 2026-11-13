"""Local engine checks using the production Delta and Structured Streaming transformations."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from edu_platform.br45 import lakehouse, oracle, spark_assessment
from edu_platform.br45.config import AnalyticsSettings
from edu_platform.br45.contracts import row_key
from edu_platform.br45.demo_dataset import build
from edu_platform.br45.engine_benchmark import compare_assessment
from edu_platform.br45.streaming import activity_windows, utc_window_rows
from tests.integration.test_br45 import T

pytestmark = [
    pytest.mark.spark,
    pytest.mark.skipif(
        not os.environ.get("EDU_BR45_RUN_SPARK_TESTS"),
        reason="Enable the local Spark/Delta runtime with EDU_BR45_RUN_SPARK_TESTS=1",
    ),
]


@pytest.fixture(scope="module")
def spark():
    pytest.importorskip("delta")
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.master("local[2]")
        .appName("DE261 BR45 correctness")
        .config("spark.pyspark.python", sys.executable)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.databricks.delta.snapshotPartitions", "2")
        .config("spark.ui.enabled", "false")
    )
    if jars := os.environ.get("EDU_BR45_DELTA_JARS"):
        builder = builder.config("spark.jars", jars)
    session = builder.getOrCreate()
    session.sparkContext.pythonExec = sys.executable
    session.sparkContext.setLogLevel("ERROR")
    try:
        yield session
    finally:
        session.stop()


def test_delta_correction_preserves_old_snapshot_and_matches_oracle(spark, tmp_path):
    root = str(tmp_path / "delta")
    fixture = build("spark-oracle", T)
    course = fixture["course_id"]
    rows = fixture["baseline"]
    changed = fixture["regrade"]["evaluations"][0]
    # Add a second version and one invalid evaluation alongside the fixture's
    # complete, missing, retry and infrastructure-error attempts.
    question = rows["questions"][0]
    case = rows["test_cases"][0]
    submission = rows["submissions"][0]
    evaluation = rows["evaluations"][0]
    rows["questions"].append(question | {"version": 2})
    rows["test_cases"].append(case | {"version": 2, "question_version": 2})
    rows["submissions"].append(submission | {"id": "v2", "question_version": 2})
    rows["evaluations"].append(
        evaluation
        | {
            "id": "v2-invalid",
            "submission_id": "v2",
            "test_case_version": 2,
            "is_valid_evaluation": False,
        }
    )

    def event(table, row, sequence):
        return (
            str(sequence),
            table,
            row_key(table, row),
            Decimal(sequence),
            False,
            json.dumps(row),
            None,
            sequence,
        )

    events = [
        event(table, row, sequence)
        for sequence, (table, row) in enumerate(
            ((table, row) for table, records in rows.items() for row in records), start=1
        )
    ]
    lakehouse.initialize(spark, root)
    base = spark.createDataFrame(events, lakehouse.ROW_SCHEMA)
    seq, initial_version = lakehouse.merge_batch(spark, root, base)
    correction = spark.createDataFrame(
        [event("evaluations", changed, seq + 1)] * 2, lakehouse.ROW_SCHEMA
    )
    _, corrected_version = lakehouse.merge_batch(spark, root, correction)
    assert corrected_version > initial_version
    assert spark.read.format("delta").load(root + "/accepted_changes").count() == seq + 1

    corrected = rows | {
        "evaluations": [
            changed if row["id"] == changed["id"] else row for row in rows["evaluations"]
        ]
    }
    start = T - timedelta(days=30)
    for version, expected in ((initial_version, rows), (corrected_version, corrected)):
        current = (
            spark.read.format("delta").option("versionAsOf", version).load(root + "/source_rows")
        )
        spark_assessment.register(spark, current)
        facts = spark_assessment.facts(spark, start, T, course)
        qs, ts = spark_assessment.aggregate(spark, facts)
        compare_assessment(
            ([r.asDict() for r in qs.collect()], [r.asDict() for r in ts.collect()]),
            oracle.assessment(expected, start, T, course),
        )


def test_spark_window_checkpoint_deduplicates_after_restart(spark, tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    checkpoint = str(tmp_path / "checkpoint")
    observed: dict[tuple[str, str, Any], int] = {}

    def write(file: str, *events: dict[str, Any]) -> None:
        # File streaming is used here to verify state with the same Spark operators.
        draft = Path(tmp_path, file)
        draft.write_text("".join(json.dumps(event) + "\n" for event in events))
        draft.replace(source / file)

    def event(event_id: str, days: int, delta: int = 1) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "student_id": "s",
            "course_id": "c",
            "event_time": (T - timedelta(days=days)).isoformat(),
            "delta": delta,
        }

    def store(batch, _batch_id):
        for row in utc_window_rows(batch).collect():
            end = datetime.fromtimestamp(row.end_seconds, UTC)
            observed[(row.student_id, row.course_id, end)] = row.activity_count

    def query():
        events = spark.readStream.schema(
            "event_id string,student_id string,course_id string,event_time timestamp,delta int"
        ).json(str(source))
        return (
            activity_windows(events, AnalyticsSettings(slide_seconds=86400))
            .writeStream.outputMode("update")
            .foreachBatch(store)
            .option("checkpointLocation", checkpoint)
            .trigger(availableNow=True)
            .start()
        )

    first = event("before", 2)
    earlier = event("older", 4)
    boundary = T.replace(hour=0)
    write("01.json", first, first, earlier)
    first_query = query()
    assert first_query.awaitTermination(90)
    assert observed[("s", "c", boundary)] == 2
    added, retracted = event("new", 3), event("retract", 4, -1)
    write("02.json", first, added, retracted)
    second_query = query()
    assert second_query.awaitTermination(90)
    expected = oracle.windows([first, earlier, added, retracted], [boundary])
    assert observed[("s", "c", boundary)] == expected[("s", "c", boundary)]
