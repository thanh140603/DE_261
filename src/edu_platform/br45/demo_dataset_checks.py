"""Expected results and evidence collection for the synthetic BR45 walkthrough."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psycopg

from .config import settings
from .contracts import timestamp
from .db import connect


def expected_results(course: str, at: datetime, recovered_at: datetime) -> dict[str, Any]:
    def metric(passed: int, valid: int, students: int, status: str, **extra: Any) -> dict[str, Any]:
        return {
            "total_valid_evaluations": valid,
            "passed_evaluations": passed,
            "failed_evaluations": valid - passed,
            "unique_students": students,
            "pass_rate": passed / valid,
            "state": status,
            **extra,
        }

    normalize = metric(
        24,
        28,
        24,
        "NORMAL",
        invalid_evaluations=2,
        infrastructure_errors=1,
        first_attempts=24,
        first_passes=20,
        first_attempt_pass_rate=20 / 24,
        latest_attempts=24,
        latest_passes=24,
        latest_attempt_pass_rate=1,
    )
    expected_questions = {
        f"{course}-normalize": normalize,
        f"{course}-sum-even": metric(2, 24, 24, "LOW_PASS_RATE"),
        f"{course}-csv-headers": metric(5, 5, 5, "INSUFFICIENT_DATA"),
    }
    expected_cases = {
        f"{course}-case-normalize": metric(24, 28, 24, "NORMAL"),
        f"{course}-case-csv-headers": metric(5, 5, 5, "INSUFFICIENT_DATA"),
        f"{course}-case-empty-input": metric(2, 24, 24, "SUSPICIOUS_TEST_CASE"),
        f"{course}-case-large-input": metric(24, 24, 24, "NORMAL"),
        f"{course}-case-mixed-input": metric(24, 24, 24, "NORMAL"),
    }

    target = f"{course}-needs-outreach"
    deadlines = {"missed_deadlines": 30, "low_completion": 20}
    prior = at.isoformat()
    later = recovered_at.isoformat()

    def risk(
        score: int,
        level: str,
        recent: int,
        previous: int,
        missed: int,
        reasons: dict[str, int],
        **features: Any,
    ) -> dict[str, Any]:
        return {
            "score": score,
            "level": level,
            "eligible": True,
            "reasons": [[signal, points] for signal, points in sorted(reasons.items())],
            "features": {
                "activity_7d": recent,
                "activity_previous_7d": previous,
                "activity_14d": recent + previous,
                "missed_deadlines_14d": missed,
                "due_assignments_14d": 1,
                "submission_rate_14d": 0 if missed else 1,
                **features,
            },
        }

    learner_risks = {
        target: risk(
            100,
            "CRITICAL",
            0,
            4,
            1,
            deadlines | {"inactivity": 35, "activity_decline": 15},
            activity_decline=1,
        ),
        f"{course}-missed-deadline": risk(50, "MEDIUM", 1, 0, 1, deadlines),
        f"{course}-learner-24": risk(
            0, "LOW", 0, 0, 0, {}, inactivity_days=None, last_activity_at=None
        ),
        f"{course}-new-enrollment": {
            "score": 0,
            "level": "LOW",
            "eligible": False,
            "reasons": [],
            "features": {"due_assignments_14d": 0},
        },
    }
    baseline: dict[str, Any] = {
        "evaluated_at": prior,
        "questions": expected_questions,
        "test_cases": expected_cases,
        "anomalies": sorted([f"{course}-sum-even", f"{course}-case-empty-input"]),
        "risk": learner_risks,
        "summary": {"monitored": 27, "levels": {"LOW": 25, "MEDIUM": 1, "HIGH": 0, "CRITICAL": 1}},
        "alert": {"status": "NEW", "student_id": target, "score": 100, "level": "CRITICAL"},
        "alert_count": 1,
        "risk_history": {prior: {"100": True}},
        "cdc": {"regraded_evaluations": 0, "recovery_activities": 0},
    }
    regrade = baseline | {
        "questions": expected_questions | {f"{course}-sum-even": metric(22, 24, 24, "NORMAL")},
        "test_cases": expected_cases | {f"{course}-case-empty-input": metric(22, 24, 24, "NORMAL")},
        "anomalies": [],
        "cdc": {"regraded_evaluations": 20, "recovery_activities": 0},
    }
    acknowledged = regrade | {
        "alert": baseline["alert"]
        | {"status": "ACKNOWLEDGED", "acknowledged_by": f"{course}-advisor"}
    }
    reengage = acknowledged | {
        "evaluated_at": later,
        "risk": learner_risks
        | {target: risk(50, "MEDIUM", 4, 4, 1, deadlines, activity_decline=0)},
        "summary": {"monitored": 27, "levels": {"LOW": 25, "MEDIUM": 2, "HIGH": 0, "CRITICAL": 0}},
        "alert": acknowledged["alert"]
        | {"status": "RESOLVED", "resolved_by": "system:risk-recovery"},
        "risk_history": {prior: {"100": True}, later: {"50": True}},
        "cdc": {"regraded_evaluations": 20, "recovery_activities": 4},
    }
    return {
        "baseline": baseline,
        "regrade": regrade,
        "acknowledged": acknowledged,
        "reengage": reengage,
    }


def api_get(base_url: str, role: str, path: str, **params: str) -> dict[str, Any]:
    request = Request(
        f"{base_url.rstrip('/')}/api/{path}?{urlencode(params)}",
        headers={"Authorization": f"Bearer br45-{role}-demo"},
    )
    with urlopen(request, timeout=8) as response:
        result: dict[str, Any] = json.load(response)
    return result


def cdc_observations(dataset: dict[str, Any]) -> dict[str, int]:
    # Count source IDs in WAL envelopes, so Kafka replays cannot inflate evidence counts.
    regrade = [row["id"] for row in dataset["regrade"]["evaluations"]]
    recovery = [row["id"] for row in dataset["reengage"]["activity_events"]]
    prefix = settings().topic_prefix
    with connect() as conn:
        observed = conn.execute(
            """
            SELECT
              count(DISTINCT envelope->'after'->>'id') FILTER (
                WHERE envelope->'source'->>'table' = 'evaluations'
                  AND envelope->>'op' = 'u'
                  AND envelope->'before'->>'status' = 'failed'
                  AND envelope->'after'->>'status' = 'passed'
                  AND envelope->'after'->>'id' = ANY(%s)
              ) AS regraded_evaluations,
              count(DISTINCT envelope->'after'->>'id') FILTER (
                WHERE envelope->'source'->>'table' = 'activity_events'
                  AND envelope->>'op' = 'c'
                  AND envelope->'after'->>'id' = ANY(%s)
              ) AS recovery_activities
            FROM analytics.raw_changes
            WHERE topic IN (%s, %s)
              AND envelope->'after'->>'id' = ANY(%s)
              AND envelope->'source'->>'lsn' IS NOT NULL
            """,
            (
                regrade,
                recovery,
                prefix + "evaluations",
                prefix + "activity_events",
                regrade + recovery,
            ),
        ).fetchone()
    assert observed is not None
    return observed


def collect(base_url: str, dataset: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    course = dataset["course_id"]
    target = expected["alert"]["student_id"]
    for role in ("instructor", "advisor"):
        session = api_get(base_url, role, "analytics/session")
        if [row["id"] for row in session["courses"]] != [course]:
            raise ValueError(f"The {role} session must show only the generated course")
    questions = api_get(base_url, "instructor", f"instructor/courses/{course}/questions/statistics")
    question_items = {row["question_id"]: row for row in questions["items"]}
    cases = {
        row["test_case_id"]: row
        for question in question_items
        for row in api_get(base_url, "instructor", f"instructor/questions/{question}/test-cases")[
            "items"
        ]
    }
    anomalies = api_get(base_url, "instructor", f"instructor/courses/{course}/anomalies")
    risk = api_get(base_url, "advisor", f"advisor/courses/{course}/at-risk-students")
    alerts = api_get(base_url, "advisor", "advisor/alerts", course_id=course)
    history = api_get(
        base_url, "advisor", f"advisor/students/{target}/risk-history", course_id=course
    )
    history_by_time: dict[str, dict[str, bool]] = {}
    for row in history["items"]:
        history_by_time.setdefault(timestamp(row["evaluated_at"]).isoformat(), {})[
            str(row["score"])
        ] = True
    return {
        "evaluated_at": timestamp(questions["window_end"]).isoformat(),
        "questions": question_items,
        "test_cases": cases,
        "anomalies": sorted(
            row.get("test_case_id") or row["question_id"] for row in anomalies["items"]
        ),
        "risk": {
            row["student_id"]: row
            | {
                "reasons": sorted(
                    [reason["signal"], reason["points"]] for reason in row["reasons"]
                ),
                "evaluated_at": timestamp(row["evaluated_at"]).isoformat(),
            }
            for row in risk["items"]
            if row["student_id"] in expected["risk"]
        },
        "summary": risk["summary"],
        "alert": next((row for row in alerts["items"] if row["student_id"] == target), {}),
        "alert_count": alerts["total"],
        "risk_history": history_by_time,
        "cdc": cdc_observations(dataset),
    }


def differences(expected: Any, actual: Any, key: str = "") -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        errors = []
        for field, value in expected.items():
            path = f"{key}.{field}" if key else field
            if field in actual:
                errors.extend(differences(value, actual[field], path))
            else:
                errors.append(f"{path} is missing")
        return errors
    if expected == actual:
        return []
    return [f"{key} expected {expected!r}, got {actual!r}"]


def verify(path: Path, dataset: dict[str, Any], stage: str, base_url: str, timeout: int) -> None:
    evidence_path = path.with_name(path.stem + "_evidence.json")
    evidence = (
        json.loads(evidence_path.read_text())
        if evidence_path.exists()
        else {
            "synthetic": True,
            "run_id": dataset["run_id"],
            "course_id": dataset["course_id"],
            "anchor": dataset["anchor"],
            "stages": {},
        }
    )
    expected = dataset["expected"][stage]
    deadline = time.monotonic() + timeout
    observed = None
    while True:
        try:
            observed = collect(base_url, dataset, expected)
            errors = differences(expected, observed)
            previous_ids = {
                saved["observed"]["alert"]["id"]
                for name, saved in evidence["stages"].items()
                if name != stage and saved["status"] == "PASS"
            }
            if previous_ids and observed["alert"].get("id") not in previous_ids:
                errors.append("The alert ID changed across checkpoints")
        except (ValueError, KeyError, psycopg.Error, OSError) as exc:
            errors = [str(exc)]
        if not errors or time.monotonic() >= deadline:
            break
        time.sleep(2)
    evidence["stages"][stage] = {
        "status": "FAIL" if errors else "PASS",
        "checked_at": datetime.now(UTC).isoformat(),
        "expected": expected,
        "observed": observed,
        "errors": errors,
    }
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"{evidence['stages'][stage]['status']} {stage}. Evidence: {evidence_path}")
    if errors:
        raise ValueError("\n".join(errors))
