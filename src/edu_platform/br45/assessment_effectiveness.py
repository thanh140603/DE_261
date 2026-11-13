"""Run labeled synthetic BR4 scenarios through PostgreSQL and the source oracle."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .assessment import refresh
from .benchmark import bulk
from .contracts import row_key
from .db import connect, migrate
from .demo_dataset import build
from .effectiveness import metrics
from .engine_benchmark import compare_assessment
from .oracle import assessment

AT = datetime(2026, 10, 16, 12, tzinfo=UTC)


def evaluate() -> dict[str, Any]:
    fixture = build("labeled-br4", AT)
    course = fixture["course_id"]
    rows = fixture["baseline"]
    # Copy the well-supported question to construct a genuinely difficult assessment.
    original = f"{course}-normalize"
    difficult = f"{course}-difficult"
    original_test = f"{course}-case-normalize"
    difficult_test = f"{course}-case-difficult"
    question = next(row for row in rows["questions"] if row["id"] == original)
    test = next(row for row in rows["test_cases"] if row["id"] == original_test)
    rows["questions"].append(question | {"id": difficult, "title": "Difficult join exercise"})
    rows["test_cases"].append(test | {"id": difficult_test, "question_id": difficult})
    selected = [
        row
        for row in rows["submissions"]
        if row["question_id"] == original and "-submission-normalize-" in row["id"]
    ]
    evaluation_by_submission = {
        row["submission_id"]: row
        for row in rows["evaluations"]
        if row["test_case_id"] == original_test
    }
    for index, submission in enumerate(selected):
        new_id = submission["id"].replace("-normalize-", "-difficult-")
        rows["submissions"].append(submission | {"id": new_id, "question_id": difficult})
        evaluation = evaluation_by_submission[submission["id"]]
        rows["evaluations"].append(
            evaluation
            | {
                "id": new_id + "-result",
                "submission_id": new_id,
                "test_case_id": difficult_test,
                "status": "passed" if index < 4 else "failed",
            }
        )
    labels = (
        ("suspicious test", f"{course}-case-empty-input", "SUSPICIOUS_TEST_CASE"),
        ("difficult question", difficult, "LOW_PASS_RATE"),
        ("normal assessment", original, "NORMAL"),
        ("insufficient sample", f"{course}-csv-headers", "INSUFFICIENT_DATA"),
    )
    start = AT - timedelta(days=30)
    migrate()
    with connect() as conn:
        bulk(
            conn,
            [(table, row_key(table, row), row) for table, data in rows.items() for row in data],
        )
        questions, cases = refresh(conn, start, AT, course)
        compare_assessment((questions, cases), assessment(rows, start, AT, course))
        conn.rollback()

    published = {row.get("test_case_id", row["question_id"]): row for row in questions + cases}
    flagged = {"LOW_PASS_RATE", "SUSPICIOUS_TEST_CASE", "NEEDS_REVIEW"}
    scenarios = [
        {
            "scenario": label,
            "expected": expected,
            "observed": published[key]["state"],
            "label": int(expected in flagged),
            "predicted": int(published[key]["state"] in flagged),
            "students": published[key]["unique_students"],
            "pass_rate": published[key]["pass_rate"],
            "lead_days": 0,
        }
        for label, key, expected in labels
    ]
    confusion = metrics(scenarios, "predicted", 1)
    return {
        "synthetic": True,
        "engine": "postgres",
        "independent_source_oracle": "PASS",
        "status": "PASS" if all(s["expected"] == s["observed"] for s in scenarios) else "FAIL",
        "scenarios": scenarios,
        "detection": {
            key: confusion[key] for key in ("tp", "fp", "tn", "fn", "precision", "recall", "f1")
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    raise SystemExit(0 if report["status"] == "PASS" else 1)
