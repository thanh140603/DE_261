"""Isolated BR4 PostgreSQL/Spark and BR5 Spark/Flink benchmark harness."""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import time
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode, urlparse

from edu_platform.br45 import oracle, spark_assessment
from edu_platform.br45.assessment import publish, refresh
from edu_platform.br45.benchmark import generate
from edu_platform.br45.config import settings
from edu_platform.br45.contracts import timestamp
from edu_platform.br45.db import Db, clean, connect, state
from edu_platform.br45.demo_dataset import apply, build

POLL = 0.25
DAY = timedelta(days=1)
SIZES = (1000, 10000, 100000)
BR4_FIXTURE = "engine-comparison"
BR4_COURSE = f"de261-br45-{BR4_FIXTURE}"
log = logging.getLogger(__name__)


def require_isolation() -> None:
    cfg = settings()
    if not cfg.engine_benchmark or urlparse(cfg.dsn).path != "/br45_bench":
        raise ValueError("Use only the isolated br45_bench database with benchmark mode enabled")


def wait(check: Callable[[], Any], label: str, timeout: int = 180) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := check():
            return result
        time.sleep(POLL)
    raise TimeoutError(label)


def api(path: str, role: str, **params: Any) -> dict[str, Any]:
    url = os.environ.get("BR45_BENCH_API", "http://127.0.0.1:18001")
    request = urllib.request.Request(
        f"{url}/api/{path}?{urlencode(params)}", headers={"Authorization": f"Bearer {role}-demo"}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data: dict[str, Any] = json.load(response)
        return data
    except URLError as exc:
        if isinstance(exc, urllib.error.HTTPError) and exc.code not in {404, 503}:
            raise
        return {}


class Journal:
    def __init__(self, output: Path, suite: str, engine: str, run_id: str) -> None:
        self.output = output
        self.rows: list[dict[str, Any]] = []
        self.meta = {
            "suite": suite,
            "engine": engine,
            "run_id": run_id,
            "measured_at": datetime.now(UTC).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "poll_seconds": POLL,
            "source_revision": os.environ.get("BR45_BENCH_REVISION"),
        }

    def write(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        draft = self.output.with_suffix(".tmp")
        draft.write_text(json.dumps(self.meta | {"trials": self.rows}, indent=2) + "\n")
        draft.replace(self.output)

    def trial(
        self,
        phase: str,
        records: int,
        repetition: int,
        operation: Callable[[], dict[str, Any]],
    ) -> bool:
        row = {"phase": phase, "records": records, "repeat": repetition}
        try:
            row |= {"status": "PASS", **operation()}
        except TimeoutError as exc:
            row |= {"status": "TIMEOUT", "error": str(exc)}
        except Exception as exc:
            log.exception("Benchmark %s failed", phase)
            row |= {"status": "FAIL", "error": str(exc)[:1000]}
        self.rows.append(row)
        self.write()
        print(self.meta["engine"], row, flush=True)
        return row["status"] == "PASS"


def compare_assessment(
    actual: tuple[list[dict[str, Any]], list[dict[str, Any]]],
    expected: dict[str, list[dict[str, Any]]],
) -> None:
    for rows, reference in zip(actual, (expected["questions"], expected["cases"]), strict=True):

        def key(row: dict[str, Any]) -> tuple[Any, ...]:
            return (
                row["course_id"],
                row["assignment_id"],
                row["question_id"],
                row["question_version"],
                row.get("test_case_id"),
                row.get("test_case_version"),
            )

        indexed = {key(row): row for row in rows}
        if len(indexed) != len(reference):
            raise AssertionError(
                f"Assessment row count differs: {len(indexed)} != {len(reference)}"
            )
        for row in reference:
            observed = indexed[key(row)]
            for field, expected_value in row.items():
                if observed[field] != expected_value:
                    raise AssertionError(
                        f"{key(row)} {field}: {observed[field]} != {expected_value}"
                    )


def spark_compute(
    spark: Any,
    conn: Db,
    course: str,
    start: datetime,
    end: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cfg = settings()
    dsn = urlparse(cfg.dsn)
    current = spark.read.jdbc(
        f"jdbc:postgresql://{dsn.hostname}:{dsn.port or 5432}{dsn.path}",
        "(SELECT table_name, data::text AS data, deleted FROM analytics.clean_rows) source_rows",
        properties={
            "user": dsn.username,
            "password": dsn.password,
            "driver": "org.postgresql.Driver",
        },
    ).persist()
    try:
        spark_assessment.register(spark, current)

        def period(
            first: datetime, last: datetime
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            facts = spark_assessment.facts(spark, first, last, course).persist()
            try:
                questions, cases = spark_assessment.aggregate(spark, facts)
                return [row.asDict() for row in questions.collect()], [
                    row.asDict() for row in cases.collect()
                ]
            finally:
                facts.unpersist()

        questions, cases = period(start, end)
        prev_questions, prev_cases = period(start - (end - start), start)
        return publish(conn, questions, cases, prev_questions + prev_cases, start, end, course, cfg)
    finally:
        current.unpersist()


def compute(
    spark: Any,
    course: str,
    start: datetime,
    end: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with connect() as conn:
        if spark is None:
            return refresh(conn, start, end, course)
        return spark_compute(spark, conn, course, start, end)


def reference(
    conn: Db, start: datetime, end: datetime, course: str
) -> dict[str, list[dict[str, Any]]]:
    return oracle.assessment(
        {
            table: clean(conn, table)
            for table in ("assignments", "questions", "test_cases", "submissions", "evaluations")
        },
        start,
        end,
        course,
    )


def br4_stage(spark: Any, journal: Journal, sizes: tuple[int, ...], repetitions: int) -> None:
    end = datetime(2026, 10, 16, 12, tzinfo=UTC)
    start = end - 30 * DAY
    for size in sizes:
        with connect() as conn:
            conn.execute("DELETE FROM analytics.clean_rows WHERE lsn=0")
            generate(conn, size, end)
            conn.execute("ANALYZE analytics.clean_rows")
            expected = reference(conn, start, end, "bench-c")
        # One warm run per size, followed by measured publications with fresh revisions.
        for repetition in range(repetitions + 1):

            def operation(expected: dict[str, list[dict[str, Any]]] = expected) -> dict[str, Any]:
                with connect() as conn:
                    state(conn, "assessment_source_revision", f"benchmark-{time.time_ns()}")
                started = time.perf_counter()
                rows = compute(spark, "bench-c", start, end)
                elapsed = (time.perf_counter() - started) * 1000
                compare_assessment(rows, expected)
                return {"elapsed_ms": elapsed}

            phase = "warmup" if repetition == 0 else "processing"
            journal.trial(phase, size, repetition, operation)


def br4_e2e(spark: Any, journal: Journal, repetitions: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM analytics.clean_rows WHERE lsn=0")
        existing = state(conn, "evaluation_clock")
        end = (
            timestamp(existing)
            if existing
            else datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        )
        fixture = build(BR4_FIXTURE, end)
        apply(conn, fixture, "baseline")
    start = end - 30 * DAY
    changed = fixture["regrade"]["evaluations"][0]["id"]
    question = f"{BR4_COURSE}-sum-even"

    def seen(status: str) -> bool:
        with connect() as conn:
            accepted = conn.execute(
                "SELECT data->>'status' AS status FROM analytics.clean_rows "
                "WHERE table_name='evaluations' AND row_key=%s AND NOT deleted",
                (changed,),
            ).fetchone()
            return bool(
                accepted and accepted["status"] == status and state(conn, "evaluation_clock")
            )

    wait(lambda: seen("failed") or seen("passed"), "CDC did not land BR4 fixture")
    for repetition in range(1, repetitions + 1):

        def operation() -> dict[str, Any]:
            with connect() as conn:
                conn.execute("UPDATE br45.evaluations SET status='failed' WHERE id=%s", (changed,))
            wait(lambda: seen("failed"), "CDC did not reset the corrected evaluation")
            with connect() as conn:
                expected_before = reference(conn, start, end, BR4_COURSE)
            compare_assessment(compute(spark, BR4_COURSE, start, end), expected_before)
            with connect() as conn:
                conn.execute("UPDATE br45.evaluations SET status='passed' WHERE id=%s", (changed,))
            started = time.perf_counter()
            wait(lambda: seen("passed"), "CDC did not land the grading correction")
            rows = compute(spark, BR4_COURSE, start, end)

            def visible() -> bool:
                result = api(
                    f"instructor/questions/{question}/statistics",
                    "instructor",
                    start=start.isoformat(),
                    end=end.isoformat(),
                )
                return any(row["passed_evaluations"] == 3 for row in result.get("items", []))

            wait(visible, "Corrected BR4 result did not reach the Instructor API")
            elapsed = (time.perf_counter() - started) * 1000
            with connect() as conn:
                expected_after = reference(conn, start, end, BR4_COURSE)
            compare_assessment(rows, expected_after)
            return {"elapsed_ms": elapsed, "passed_before": 2, "passed_after": 3}

        journal.trial("e2e_correction", 106, repetition, operation)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", choices=("postgres", "spark"))
    parser.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--e2e-repeats", type=int, default=5)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--native", action="store_true", help="Report native resource limits")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require_isolation()
    journal = Journal(args.output, "BR4", args.engine, args.run_id)
    spark = None
    try:
        if args.engine == "spark":
            from pyspark.sql import SparkSession

            spark = (
                SparkSession.builder.appName("BR4 engine benchmark")
                .config("spark.sql.session.timeZone", "UTC")
                .config("spark.sql.shuffle.partitions", "2")
                .config("spark.ui.enabled", "false")
                .getOrCreate()
            )
            spark.sparkContext.setLogLevel("WARN")
            journal.meta["engine_version"] = spark.version
        else:
            with connect() as conn:
                version = conn.execute("SHOW server_version").fetchone()
            journal.meta["engine_version"] = version["server_version"] if version else None
        journal.meta["cpu_limit"] = None if args.native else 2
        journal.meta["memory_limit_gib"] = None if args.native else 2
        journal.meta["runtime"] = "native" if args.native else "compose"
        br4_stage(spark, journal, tuple(args.sizes), args.repeats)
        if args.e2e_repeats:
            br4_e2e(spark, journal, args.e2e_repeats)
    finally:
        if spark:
            spark.stop()


if __name__ == "__main__":
    main()
