"""Reproducible measured SQL/Python and window/batch comparisons; never invented timings."""

from __future__ import annotations

import csv
import json
import os
import platform
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from .assessment import ATTEMPTS_SQL, CASES_SQL, QUESTION_SQL, enrich, python_baseline, refresh
from .db import Db, connect


def bulk(conn: Db, rows: list[tuple[str, str, dict[str, Any]]]) -> None:
    with conn.cursor().copy(
        "COPY analytics.clean_rows(table_name,row_key,data) FROM STDIN"
    ) as copy:
        for table, key, data in rows:
            copy.write_row((table, key, Jsonb(data)))


def generate(conn: Db, size: int, at: datetime) -> None:
    created = (at - timedelta(days=40)).isoformat()
    rows = [
        (
            "courses",
            "bench-c",
            {
                "id": "bench-c",
                "title": "SYNTHETIC benchmark",
                "created_at": created,
                "telemetry_enabled": True,
            },
        ),
        (
            "assignments",
            "bench-a",
            {
                "id": "bench-a",
                "course_id": "bench-c",
                "title": "Benchmark",
                "required": True,
                "deadline": None,
                "published_at": created,
            },
        ),
        (
            "questions",
            "bench-q:1",
            {
                "id": "bench-q",
                "version": 1,
                "assignment_id": "bench-a",
                "title": "Benchmark question",
                "created_at": created,
            },
        ),
    ]
    for j in range(3):
        rows.append(
            (
                "test_cases",
                f"bench-t{j}:1",
                {
                    "id": f"bench-t{j}",
                    "version": 1,
                    "question_id": "bench-q",
                    "question_version": 1,
                    "required": True,
                    "created_at": created,
                },
            )
        )
    for i in range((size + 2) // 3):
        sid = f"bench-sub-{i}"
        rows.append(
            (
                "submissions",
                sid,
                {
                    "id": sid,
                    "student_id": f"bench-student-{i % 1000}",
                    "course_id": "bench-c",
                    "assignment_id": "bench-a",
                    "question_id": "bench-q",
                    "question_version": 1,
                    "submitted_at": (at - timedelta(days=1, seconds=i)).isoformat(),
                    "execution_status": "evaluated",
                },
            )
        )
    for i in range(size):
        rows.append(
            (
                "evaluations",
                f"bench-e{i}",
                {
                    "id": f"bench-e{i}",
                    "submission_id": f"bench-sub-{i // 3}",
                    "test_case_id": f"bench-t{i % 3}",
                    "test_case_version": 1,
                    "status": "failed" if i % 3 == 1 and i % 10 else "passed",
                    "is_valid_evaluation": True,
                    "evaluated_at": (at - timedelta(hours=1)).isoformat(),
                },
            )
        )
    bulk(conn, rows)


def canonical(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)


def run(output: str, sizes: tuple[int, ...] = (1000, 10000, 100000), repetitions: int = 3) -> None:
    dest = Path(output)
    dest.mkdir(parents=True, exist_ok=True)
    at = datetime(2026, 10, 16, 12, tzinfo=UTC)
    measurements: list[dict[str, Any]] = []
    with connect() as conn:
        environment = {
            "measured_at": datetime.now(UTC).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
            "processor": platform.processor(),
            "postgres": conn.execute("SELECT version() version").fetchone(),
            "repetitions": repetitions,
            "dataset": "SYNTHETIC; 3 tests/question, repeated students, test 1 mostly failing",
            "sizes": sizes,
        }
        for size in sizes:
            # All benchmark mutations roll back; existing analytics are never replaced.
            with conn.transaction(force_rollback=True):
                conn.execute("DELETE FROM analytics.clean_rows")
                conn.execute(
                    "DELETE FROM analytics.pipeline_state WHERE key='assessment_source_revision'"
                )
                generate(conn, size, at)
                conn.execute("ANALYZE analytics.clean_rows")
                params: dict[str, Any] = {
                    "start": at - timedelta(days=30),
                    "end": at,
                    "course": "bench-c",
                }
                for repeat in range(repetitions):
                    started = time.perf_counter()
                    sq = enrich(list(conn.execute(QUESTION_SQL, params)))
                    st = enrich(list(conn.execute(CASES_SQL, params)))
                    sql_ms = (time.perf_counter() - started) * 1000
                    started = time.perf_counter()
                    pq, pt = python_baseline(list(conn.execute(ATTEMPTS_SQL, params)))
                    python_ms = (time.perf_counter() - started) * 1000
                    assert canonical(sq) == canonical(pq) and canonical(st) == canonical(pt)
                    started = time.perf_counter()
                    refresh(conn, params["start"], at, "bench-c")
                    persisted_ms = (time.perf_counter() - started) * 1000
                    started = time.perf_counter()
                    list(
                        conn.execute(
                            "SELECT data FROM analytics.mart_question_pass_statistics WHERE "
                            "course_id='bench-c' ORDER BY id LIMIT 20"
                        )
                    )
                    query_ms = (time.perf_counter() - started) * 1000
                    # Correct a stable evaluation id; no duplicate increments.
                    conn.execute(
                        "UPDATE analytics.clean_rows SET "
                        "data=jsonb_set(data,'{status}','\"passed\"') "
                        "WHERE table_name='evaluations' AND row_key='bench-e1'"
                    )
                    started = time.perf_counter()
                    refresh(conn, params["start"], at, "bench-c")
                    incremental_ms = (time.perf_counter() - started) * 1000
                    conn.execute(
                        "UPDATE analytics.clean_rows SET "
                        "data=jsonb_set(data,'{status}','\"failed\"') "
                        "WHERE table_name='evaluations' AND row_key='bench-e1'"
                    )
                    measurements.append(
                        {
                            "br": "BR4",
                            "evaluation_rows": size,
                            "repeat": repeat + 1,
                            "sql_ms": sql_ms,
                            "python_ms": python_ms,
                            "persisted_refresh_ms": persisted_ms,
                            "query_ms": query_ms,
                            "correction_refresh_ms": incremental_ms,
                            "correct": True,
                        }
                    )
                    print(
                        (
                            "BR4 "
                            f"{size}"
                            " evaluations repetition "
                            f"{repeat + 1}"
                            ": SQL "
                            f"{sql_ms:.1f}"
                            "ms; Python "
                            f"{python_ms:.1f}"
                            "ms"
                        ),
                        flush=True,
                    )
    with (dest / "br4_benchmark.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(measurements[0]))
        writer.writeheader()
        writer.writerows(measurements)
    (dest / "environment.json").write_text(json.dumps(environment, indent=2, default=str) + "\n")
    # Small standalone SVG is generated only from recorded measurements.
    points = []
    for size in sizes:
        rows = [r for r in measurements if r["evaluation_rows"] == size]
        points.append(
            (
                size,
                sum(r["sql_ms"] for r in rows) / len(rows),
                sum(r["python_ms"] for r in rows) / len(rows),
            )
        )
    maximum = max(max(p[1:]) for p in points)
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="300" viewBox="0 0 760 300">',
        '<rect width="760" height="300" fill="white"/>',
        (
            '<text x="20" y="25" font-family="sans-serif" font-size="18">BR4 measured '
            "aggregation time (mean milliseconds)</text>"
        ),
    ]
    for i, (size, sql_ms, python_ms) in enumerate(points):
        y = 55 + i * 75
        svg.extend(
            [
                f'<text x="20" y="{y + 18}" font-family="sans-serif">{size:,} evaluations</text>',
                (
                    '<rect x="180" y="'
                    f"{y}"
                    '" width="'
                    f"{sql_ms / maximum * 400:.2f}"
                    '" height="20" fill="#1f7a5a"/>'
                ),
                f'<text x="590" y="{y + 16}" font-family="sans-serif">SQL {sql_ms:.1f}</text>',
                (
                    '<rect x="180" y="'
                    f"{y + 25}"
                    '" width="'
                    f"{python_ms / maximum * 400:.2f}"
                    '" height="20" fill="#4a6fa5"/>'
                ),
                (
                    '<text x="590" y="'
                    f"{y + 41}"
                    '" font-family="sans-serif">Python '
                    f"{python_ms:.1f}"
                    "</text>"
                ),
            ]
        )
    (dest / "br4_benchmark.svg").write_text("\n".join([*svg, "</svg>"]) + "\n")
