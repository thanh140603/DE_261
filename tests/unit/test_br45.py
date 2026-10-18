from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from edu_platform.br45.assessment import classify, python_baseline
from edu_platform.br45.config import AnalyticsSettings
from edu_platform.br45.contracts import timestamp, validate_row
from edu_platform.br45.risk import score

T = datetime(2026, 10, 16, 12, tzinfo=UTC)
CFG = AnalyticsSettings()


def risk(recent=0, previous=4, *, age=30, deadlines=True, telemetry=True, activity=True):
    en = {
        "student_id": "s",
        "course_id": "c",
        "status": "active",
        "enrolled_at": (T - timedelta(days=age)).isoformat(),
    }
    assignments = (
        [
            {
                "id": "a",
                "course_id": "c",
                "required": True,
                "deadline": (T - timedelta(days=2)).isoformat(),
                "published_at": (T - timedelta(days=20)).isoformat(),
            }
        ]
        if deadlines
        else []
    )
    activities = (
        [{"student_id": "s", "course_id": "c", "event_time": (T - timedelta(days=8)).isoformat()}]
        if activity
        else []
    )
    return score(
        en, {"telemetry_enabled": telemetry}, assignments, [], activities, T, recent, previous, CFG
    )


def test_risk_explainable_and_capped():
    r = risk()
    assert r["score"] == 100 and r["level"] == "CRITICAL"
    assert {s["signal"] for s in r["reasons"]} == {
        "inactivity",
        "missed_deadlines",
        "low_completion",
        "activity_decline",
    }


def test_new_learner_and_missing_telemetry_are_not_assumed_inactive():
    assert risk(age=2)["score"] == 0
    assert risk(telemetry=False)["score"] == 50
    assert risk(activity=False, previous=0)["score"] == 50
    assert risk(activity=False, previous=0, deadlines=False)["score"] == 0


def test_reference_floor_no_future_or_not_yet_due_penalty():
    assert "activity_decline" not in {r["signal"] for r in risk(previous=2)["reasons"]}
    en = {
        "student_id": "s",
        "course_id": "c",
        "status": "active",
        "enrolled_at": (T - timedelta(days=20)).isoformat(),
    }
    a = [
        {
            "id": "future",
            "course_id": "c",
            "required": True,
            "deadline": (T + timedelta(days=1)).isoformat(),
            "published_at": T.isoformat(),
        }
    ]
    events = [
        {"student_id": "s", "course_id": "c", "event_time": (T + timedelta(seconds=1)).isoformat()}
    ]
    r = score(en, {"telemetry_enabled": True}, a, [], events, T, 0, 0, CFG)
    assert r["score"] == 0 and r["features"]["due_assignments_14d"] == 0


@pytest.mark.parametrize(
    ("students", "value", "expected"),
    [
        (19, 0, "INSUFFICIENT_DATA"),
        (20, 0, "LOW_PASS_RATE"),
        (20, 1, "NORMAL"),
        (20, 0.3, "NORMAL"),
    ],
)
def test_anomaly_thresholds(students, value, expected):
    row = {"unique_students": students, "pass_rate": value}
    assert classify(row, [], None, CFG)["state"] == expected


def test_peer_comparison_and_previous_window_drop():
    row = {"test_case_id": "t", "unique_students": 20, "pass_rate": 0.1}
    assert (
        classify(row, [row, {"unique_students": 20, "pass_rate": 1}], None, CFG)["state"]
        == "SUSPICIOUS_TEST_CASE"
    )
    assert (
        classify(
            {"unique_students": 20, "pass_rate": 0.5},
            [],
            {"unique_students": 20, "pass_rate": 1},
            CFG,
        )["state"]
        == "NEEDS_REVIEW"
    )


def test_contracts_reject_missing_ids_status_and_naive_time():
    with pytest.raises(ValueError):
        timestamp("2026-10-16T12:00:00")
    with pytest.raises(ValueError):
        validate_row(
            "activity_events",
            {
                "id": "",
                "student_id": "s",
                "course_id": "c",
                "event_type": "invented",
                "event_time": T.isoformat(),
            },
        )
    assert timestamp(0) == datetime(1970, 1, 1, tzinfo=UTC)


def test_active_learner_and_recovery_use_observed_activity():
    en = {
        "student_id": "s",
        "course_id": "c",
        "status": "active",
        "enrolled_at": (T - timedelta(days=30)).isoformat(),
    }
    activities = [
        {"student_id": "s", "course_id": "c", "event_time": (T - timedelta(days=1)).isoformat()}
    ]
    assert score(en, {"telemetry_enabled": True}, [], [], activities, T, 4, 4, CFG)["score"] == 0
    inactive = score(
        en, {"telemetry_enabled": True}, [], [], activities, T + timedelta(days=8), 0, 4, CFG
    )
    assert inactive["score"] == 50
    assert {r["signal"] for r in inactive["reasons"]} == {"inactivity", "activity_decline"}
    activities.append(
        {
            "student_id": "s",
            "course_id": "c",
            "event_time": (T + timedelta(days=8) - timedelta(minutes=1)).isoformat(),
        }
    )
    assert (
        score(
            en, {"telemetry_enabled": True}, [], [], activities, T + timedelta(days=8), 4, 4, CFG
        )["score"]
        == 0
    )
    assert (
        score(
            {**en, "status": "completed"},
            {"telemetry_enabled": True},
            [],
            [],
            activities,
            T,
            0,
            4,
            CFG,
        )["eligible"]
        is False
    )


def test_only_due_required_assignments_affect_submission_rate():
    en = {
        "student_id": "s",
        "course_id": "c",
        "status": "active",
        "enrolled_at": (T - timedelta(days=30)).isoformat(),
    }
    a = [
        {
            "id": "a",
            "course_id": "c",
            "required": True,
            "deadline": (T - timedelta(days=1)).isoformat(),
            "published_at": (T - timedelta(days=2)).isoformat(),
        }
    ]
    submissions = [
        {
            "student_id": "s",
            "course_id": "c",
            "assignment_id": "a",
            "submitted_at": (T - timedelta(days=2)).isoformat(),
            "execution_status": "pending",
        }
    ]
    result = score(en, {"telemetry_enabled": False}, a, submissions, [], T, 0, 0, CFG)
    assert result["score"] == 0 and result["features"]["submission_rate_14d"] == 1
    assert (
        score(
            en, {"telemetry_enabled": False}, [{**a[0], "required": False}], [], [], T, 0, 0, CFG
        )["features"]["submission_rate_14d"]
        is None
    )


def test_reference_first_latest_multiple_cases_and_invalid_attempts():
    rows = []
    for sid, student, at, passes, valid in [
        ("1", "s", 1, False, True),
        ("2", "s", 2, True, True),
        ("3", "z", 3, False, False),
    ]:
        for case in ("a", "b"):
            rows.append(
                {
                    "submission_id": sid,
                    "student_id": student,
                    "course_id": "c",
                    "assignment_id": "a",
                    "question_id": "q",
                    "question_version": 1,
                    "question_title": "Q",
                    "assignment_title": "A",
                    "submitted_at": str(at),
                    "test_case_id": case,
                    "test_case_version": 1,
                    "status": "passed" if passes or case == "a" else "failed",
                    "valid": valid,
                    "infra_error": not valid,
                }
            )
    q, t = python_baseline(rows)
    assert q[0]["total_valid_evaluations"] == 2
    assert q[0]["first_attempt_pass_rate"] == 0 and q[0]["latest_attempt_pass_rate"] == 1
    assert q[0]["unique_students"] == 1 and q[0]["infrastructure_errors"] == 1
    assert sorted(r["pass_rate"] for r in t) == [0.5, 1]
