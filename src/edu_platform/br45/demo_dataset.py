"""Build and replay the synthetic DE_261 assessment and intervention walkthrough."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from .config import AnalyticsSettings, settings
from .contracts import CONTRACTS, timestamp, validate_row
from .db import Db, connect, state
from .demo_dataset_checks import expected_results, verify

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
STAGES = ("baseline", "regrade", "reengage")
OUTPUT = Path("data/br45-demo")


def build(run_id: str, at: datetime) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", run_id) or len(run_id) > 24:
        raise ValueError("Use a run ID of up to 24 lowercase letters, digits, and hyphens")
    at = timestamp(at)
    if at != at.replace(minute=0, second=0, microsecond=0):
        raise ValueError("Use an evaluation time on a UTC hour boundary")
    course = f"de261-br45-{run_id}"
    rows: dict[str, list[dict[str, Any]]] = {table: [] for table in CONTRACTS}

    def add(table: str, suffix: str, **fields: Any) -> str:
        key = f"{course}-{suffix}" if suffix else course
        rows[table].append(validate_row(table, {"id": key, **fields}))
        return key

    created = at - 35 * DAY
    add(
        "courses",
        "",
        title=f"SYNTHETIC · Python for Data ({run_id})",
        telemetry_enabled=True,
        created_at=created,
    )
    due = add(
        "assignments",
        "assignment-data",
        course_id=course,
        title="Data cleaning lab",
        published_at=created,
        deadline=at - 2 * DAY,
        required=True,
    )
    future = add(
        "assignments",
        "assignment-practice",
        course_id=course,
        title="CSV practice",
        published_at=at - 5 * DAY,
        deadline=at + 2 * DAY,
        required=True,
    )
    healthy = add(
        "questions",
        "normalize",
        assignment_id=due,
        title="Normalize input rows",
        version=1,
        created_at=created,
    )
    flagged = add(
        "questions",
        "sum-even",
        assignment_id=due,
        title="Sum even numbers",
        version=1,
        created_at=created,
    )
    practice = add(
        "questions",
        "csv-headers",
        assignment_id=future,
        title="Validate CSV headers",
        version=1,
        created_at=at - 5 * DAY,
    )
    cases = {}
    for name, question in (
        ("normalize", healthy),
        ("mixed-input", flagged),
        ("empty-input", flagged),
        ("large-input", flagged),
        ("csv-headers", practice),
    ):
        cases[name] = add(
            "test_cases",
            f"case-{name}",
            question_id=question,
            question_version=1,
            version=1,
            required=True,
            created_at=at - 5 * DAY if question == practice else created,
        )

    def enroll(name: str, age: int = 30) -> str:
        student = f"{course}-{name}"
        add(
            "enrollments",
            f"enrollment-{name}",
            student_id=student,
            course_id=course,
            status="active",
            enrolled_at=at - age * DAY,
        )
        return student

    def activity(suffix: str, student: str, when: datetime) -> str:
        return add(
            "activity_events",
            suffix,
            student_id=student,
            course_id=course,
            event_type="lesson_complete",
            event_time=when,
        )

    def attempt(
        name: str,
        student: str,
        question: str,
        when: datetime,
        results: dict[str, str],
        execution_status: str = "evaluated",
    ) -> None:
        submission = add(
            "submissions",
            f"submission-{name}",
            student_id=student,
            course_id=course,
            assignment_id=future if question == practice else due,
            question_id=question,
            question_version=1,
            submitted_at=when,
            execution_status=execution_status,
        )
        for case, status in results.items():
            add(
                "evaluations",
                f"evaluation-{name}-{case}",
                submission_id=submission,
                test_case_id=cases[case],
                test_case_version=1,
                status=status,
                is_valid_evaluation=status != "infra_error",
                evaluated_at=when + timedelta(seconds=30),
            )

    for number in range(1, 25):
        student = enroll(f"learner-{number:02}")
        attempt(
            f"normalize-{number:02}",
            student,
            healthy,
            at - 4 * DAY,
            {"normalize": "passed" if number <= 20 else "failed"},
        )
        attempt(
            f"sum-even-{number:02}",
            student,
            flagged,
            at - 3 * DAY,
            {
                "mixed-input": "passed",
                "empty-input": "passed" if number <= 2 else "failed",
                "large-input": "passed",
            },
        )
        if number <= 5:
            attempt(f"csv-{number:02}", student, practice, at - DAY, {"csv-headers": "passed"})
        if number > 20:
            attempt(f"retry-{number:02}", student, healthy, at - 2 * DAY, {"normalize": "passed"})
        if number < 24:
            activity(f"activity-{number:02}", student, at - DAY)
    attempt("missing", f"{course}-learner-01", healthy, at - DAY, {})
    attempt(
        "infra",
        f"{course}-learner-02",
        healthy,
        at - DAY,
        {"normalize": "infra_error"},
        execution_status="infra_error",
    )
    target = enroll("needs-outreach")
    for days_ago in range(8, 12):
        activity(f"previous-{days_ago}", target, at - days_ago * DAY)
    activity("medium-recent", enroll("missed-deadline"), at - DAY)
    enroll("new-enrollment", age=1)
    clock_id = add("clocks", "clock", evaluated_at=at)

    corrected_ids = {
        f"{course}-evaluation-sum-even-{number:02}-empty-input" for number in range(3, 23)
    }
    regrade = [
        validate_row("evaluations", row | {"status": "passed"})
        for row in rows["evaluations"]
        if row["id"] in corrected_ids
    ]
    recovery = [
        validate_row(
            "activity_events",
            {
                "id": f"{course}-recovery-{minutes}",
                "student_id": target,
                "course_id": course,
                "event_type": "lesson_complete",
                "event_time": at + timedelta(minutes=minutes),
            },
        )
        for minutes in (15, 20, 25, 30)
    ]
    return {
        "schema_version": 1,
        "synthetic": True,
        "run_id": run_id,
        "course_id": course,
        "anchor": at.isoformat(),
        "auth": {
            f"br45-{role}-demo": {"id": f"{course}-{role}", "role": role, "courses": [course]}
            for role in ("instructor", "advisor")
        },
        "baseline": rows,
        "regrade": {"evaluations": regrade},
        "reengage": {
            "activity_events": recovery,
            "clocks": [validate_row("clocks", {"id": clock_id, "evaluated_at": at + HOUR})],
        },
        "expected": expected_results(course, at, at + HOUR),
    }


def read(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text())
    dataset = build(document["run_id"], timestamp(document["anchor"]))
    if document != dataset:
        raise ValueError("Dataset does not match the generated DE_261 BR45 fixture. Rebuild it.")
    return dataset


def insert_rows(conn: Db, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    query = sql.SQL("INSERT INTO br45.{} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    with conn.cursor() as cursor:
        cursor.executemany(query, [[row[column] for column in columns] for row in rows])


def preflight(conn: Db, at: datetime, activity: list[dict[str, Any]], fresh: bool = False) -> None:
    actual = state(conn, "evaluation_clock")
    if (actual is None and not fresh) or (actual is not None and timestamp(actual) != at):
        raise ValueError("Evaluation clock differs from the dataset anchor. Check the clock.")
    watermark = state(conn, "stream_watermark")
    if watermark and any(timestamp(row["event_time"]) <= timestamp(watermark) for row in activity):
        raise ValueError("Demo activity would be rejected by the Spark watermark")


def check_config() -> None:
    policy = {
        "clock_mode",
        "slide_seconds",
        "lateness_days",
        "min_students",
        "question_threshold",
        "case_threshold",
        "peer_gap",
        "drop_threshold",
        "inactivity_points",
        "missed_points",
        "completion_points",
        "decline_points",
        "medium_threshold",
        "high_threshold",
        "critical_threshold",
        "alert_threshold",
        "cooldown_hours",
    }
    # Compare environment overrides against field defaults, including the manual clock.
    model = settings()
    changed = [
        name
        for name in sorted(policy)
        if getattr(model, name) != AnalyticsSettings.model_fields[name].default
    ]
    if changed:
        raise ValueError(f"Use the default BR45 demo settings for {', '.join(changed)}")


def regrade_status(conn: Db, dataset: dict[str, Any]) -> dict[str, str]:
    ids = [row["id"] for row in dataset["regrade"]["evaluations"]]
    statuses = {
        row["id"]: row["status"]
        for row in conn.execute("SELECT id, status FROM br45.evaluations WHERE id=ANY(%s)", (ids,))
    }
    if len(statuses) != len(ids) or set(statuses.values()) - {"passed", "failed"}:
        raise ValueError("The demo evaluations are missing or have unexpected statuses")
    return statuses


def apply(conn: Db, dataset: dict[str, Any], stage: str) -> bool:
    """Apply one stage inside the caller's transaction. Return false for a completed retry."""
    if stage not in STAGES:
        raise ValueError(f"Unknown demo stage {stage!r}")
    at = timestamp(dataset["anchor"])
    course = dataset["course_id"]
    clock_id = dataset["baseline"]["clocks"][0]["id"]
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('de261-br45-demo'))")
    clock = conn.execute("SELECT evaluated_at FROM br45.clocks WHERE id=%s", (clock_id,)).fetchone()
    existing = conn.execute("SELECT created_at FROM br45.courses WHERE id=%s", (course,)).fetchone()
    if existing and existing["created_at"] != timestamp(
        dataset["baseline"]["courses"][0]["created_at"]
    ):
        raise ValueError(
            "This run ID belongs to another anchor. Build a dataset with a fresh run ID."
        )
    if stage == "baseline":
        if existing and clock:
            return False
        preflight(conn, at, dataset["baseline"]["activity_events"], fresh=True)
        for table, rows in dataset["baseline"].items():
            insert_rows(conn, table, rows)
        return True
    if not existing or not clock:
        raise ValueError("Apply the baseline stage first")
    statuses = regrade_status(conn, dataset)
    if stage == "regrade":
        pending = [key for key, value in statuses.items() if value == "failed"]
        if not pending:
            return False
        preflight(conn, at, [])
        conn.execute("UPDATE br45.evaluations SET status='passed' WHERE id=ANY(%s)", (pending,))
        return True
    end = timestamp(dataset["reengage"]["clocks"][0]["evaluated_at"])
    if clock["evaluated_at"] == end:
        return False
    if clock["evaluated_at"] != at:
        raise ValueError("The source clock for this demo run was changed")
    preflight(conn, at, dataset["reengage"]["activity_events"])
    if "failed" in statuses.values():
        raise ValueError("Apply the regrade stage before reengagement")
    acknowledged = conn.execute(
        "SELECT 1 FROM analytics.dropout_alerts WHERE course_id=%s AND student_id=%s "
        "AND status='ACKNOWLEDGED'",
        (course, f"{course}-needs-outreach"),
    ).fetchone()
    if not acknowledged:
        raise ValueError("Acknowledge the outreach learner's alert in the Advisor dashboard first")
    insert_rows(conn, "activity_events", dataset["reengage"]["activity_events"])
    conn.execute("UPDATE br45.clocks SET evaluated_at=%s WHERE id=%s", (end, clock_id))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("build", help="Export the reproducible synthetic dataset")
    create.add_argument("--run-id", required=True)
    create.add_argument("--at", type=timestamp, help="Explicit UTC hour for offline generation")
    create.add_argument("--output-dir", type=Path, default=OUTPUT)
    load = sub.add_parser("apply", help="Commit one stage to the PostgreSQL source tables")
    load.add_argument("dataset", type=Path)
    load.add_argument("stage", choices=STAGES)
    check = sub.add_parser("check", help="Verify a checkpoint and save JSON evidence")
    check.add_argument("dataset", type=Path)
    check.add_argument("stage", choices=(*STAGES, "acknowledged"))
    check.add_argument("--base-url", default="http://127.0.0.1:8001")
    check.add_argument("--timeout", type=int, default=180, metavar="SECONDS")
    args = parser.parse_args()
    try:
        if args.command == "build":
            at = args.at
            if at is None:
                check_config()
                with connect() as conn:
                    current = state(conn, "evaluation_clock")
                at = (
                    timestamp(current)
                    if current
                    else datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
                )
            dataset = build(args.run_id, at)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            path = args.output_dir / f"DE_261_BR45_{args.run_id}.json"
            with path.open("x") as out:
                out.write(json.dumps(dataset, indent=2) + "\n")
            print(path)
        elif args.command == "apply":
            check_config()
            dataset = read(args.dataset)
            with connect() as conn:
                applied = apply(conn, dataset, args.stage)
            print(f"{args.stage} {'committed to PostgreSQL' if applied else 'already applied'}")
        else:
            if args.timeout < 1:
                parser.error("--timeout must be at least 1 second")
            verify(args.dataset, read(args.dataset), args.stage, args.base_url, args.timeout)
    except (ValueError, KeyError, TypeError, OSError, psycopg.Error) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
