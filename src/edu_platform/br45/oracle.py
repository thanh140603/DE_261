"""Slow, independent reference over source tables; never imports production aggregation.

Used only for small correctness fixtures. Large-scale engines are checked by counts,
partition hashes and a bounded independently computed sample.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any


def instant(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def assessment(
    source: dict[str, list[dict[str, Any]]],
    start: datetime,
    end: datetime,
    course: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    questions = {(r["id"], r["version"]): r for r in source["questions"]}
    assignments = {r["id"]: r for r in source["assignments"]}
    evaluations = {
        (r["submission_id"], r["test_case_id"], r["test_case_version"]): r
        for r in source["evaluations"]
    }
    qgroups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    tgroups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for sub in source["submissions"]:
        at = instant(sub["submitted_at"])
        if not start <= at < end or (course and sub["course_id"] != course):
            continue
        q = questions.get((sub["question_id"], sub["question_version"]))
        assignment = assignments.get(sub["assignment_id"])
        if not q or not assignment or q["assignment_id"] != assignment["id"]:
            continue
        if assignment["course_id"] != sub["course_id"]:
            continue
        manifest: dict[str, dict[str, Any]] = {}
        for test in source["test_cases"]:
            if (test["question_id"], test["question_version"]) != (q["id"], q["version"]):
                continue
            if instant(test["created_at"]) <= at:
                old = manifest.get(test["id"])
                if old is None or old["version"] < test["version"]:
                    manifest[test["id"]] = test
        required = [t for t in manifest.values() if t["required"]]
        tests = []
        key = (sub["course_id"], sub["assignment_id"], q["id"], q["version"])
        for test in required:
            ev = evaluations.get((sub["id"], test["id"], test["version"]))
            if ev and instant(ev["evaluated_at"]) >= end:
                ev = None
            valid = bool(
                ev
                and ev["is_valid_evaluation"]
                and ev["status"] in {"passed", "failed", "error", "timeout"}
                and sub["execution_status"] == "evaluated"
            )
            item = {
                "valid": valid,
                "passed": bool(ev and ev["status"] == "passed"),
                "infra": sub["execution_status"] == "infra_error"
                or bool(ev and ev["status"] == "infra_error"),
                "student": sub["student_id"],
                "at": at,
                "id": sub["id"],
            }
            tests.append(item)
            tgroups[(*key, test["id"], test["version"])].append(item)
        qgroups[key].append(
            {
                "valid": bool(tests) and all(t["valid"] for t in tests),
                "passed": bool(tests) and all(t["passed"] for t in tests),
                "infra": sub["execution_status"] == "infra_error" or any(t["infra"] for t in tests),
                "student": sub["student_id"],
                "at": at,
                "id": sub["id"],
            }
        )

    def metrics(key: tuple[Any, ...], rows: list[dict[str, Any]]) -> dict[str, Any]:
        valid = [r for r in rows if r["valid"]]
        passed = sum(r["passed"] for r in valid)
        value = dict(
            zip(
                (
                    "course_id",
                    "assignment_id",
                    "question_id",
                    "question_version",
                    "test_case_id",
                    "test_case_version",
                ),
                key,
                strict=False,
            )
        )
        value.update(
            total_valid_evaluations=len(valid),
            passed_evaluations=passed,
            failed_evaluations=len(valid) - passed,
            invalid_evaluations=len(rows) - len(valid),
            infrastructure_errors=sum(r["infra"] for r in rows),
            unique_students=len({r["student"] for r in valid}),
            pass_rate=passed / len(valid) if valid else None,
        )
        if len(key) == 4:
            learners: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in sorted(valid, key=lambda r: (r["at"], r["id"])):
                learners[row["student"]].append(row)
            for prefix, index in (("first", 0), ("latest", -1)):
                successes = sum(rs[index]["passed"] for rs in learners.values())
                value[f"{prefix}_attempts"] = len(learners)
                value[f"{prefix}_passes"] = successes
                value[f"{prefix}_attempt_pass_rate"] = (
                    successes / len(learners) if learners else None
                )
        return value

    return {
        "questions": [metrics(k, v) for k, v in sorted(qgroups.items())],
        "cases": [metrics(k, v) for k, v in sorted(tgroups.items())],
    }


def windows(
    events: list[dict[str, Any]], ends: list[datetime], days: int = 7
) -> dict[tuple[str, str, datetime], int]:
    from datetime import timedelta

    unique = {e["event_id"]: e for e in events}
    result: dict[tuple[str, str, datetime], int] = defaultdict(int)
    for event in unique.values():
        for end in ends:
            if end - timedelta(days=days) <= instant(event["event_time"]) < end:
                result[(event["student_id"], event["course_id"], end)] += event["delta"]
    return dict(result)
