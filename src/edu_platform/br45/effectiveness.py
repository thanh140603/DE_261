"""Reproducible, time-separated OULAD evaluation. No training labels enter features.

OULAD is daily aggregated telemetry. A sum_click is a weight, not a fabricated
collection of timestamped browser events. Day T features use observations with day < T.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import platform
import subprocess
import zipfile
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import AnalyticsSettings
from .risk import score

CUTOFFS = (14, 28, 56)
ORIGIN = datetime(2000, 1, 1, tzinfo=UTC)  # relative-day arithmetic only, never claimed real dates


def records(archive: zipfile.ZipFile, name: str) -> Any:
    with archive.open(name) as stream:
        yield from csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig"))


def key(row: dict[str, Any]) -> tuple[str, str, str]:
    return row["code_module"], row["code_presentation"], row["id_student"]


def metrics(rows: list[dict[str, Any]], field: str, threshold: float) -> dict[str, Any]:
    tp = sum(r["label"] == 1 and r[field] >= threshold for r in rows)
    fp = sum(r["label"] == 0 and r[field] >= threshold for r in rows)
    fn = sum(r["label"] == 1 and r[field] < threshold for r in rows)
    tn = len(rows) - tp - fp - fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    groups: dict[float, list[int]] = defaultdict(list)
    for row in rows:
        groups[row[field]].append(row["label"])
    positives = tp + fn
    seen = hits = 0
    ap = 0.0
    for value in sorted(groups, reverse=True):
        labels = groups[value]
        seen += len(labels)
        new_hits = sum(labels)
        hits += new_hits
        if positives:
            ap += new_hits / positives * hits / seen
    leads = sorted(r["lead_days"] for r in rows if r["label"] and r[field] >= threshold)
    import statistics

    return {
        "n": len(rows),
        "positives": positives,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "pr_auc_average_precision": ap,
        "alerts": tp + fp,
        "alert_fraction": (tp + fp) / len(rows) if rows else 0.0,
        "median_lead_days": statistics.median(leads) if leads else None,
        "threshold": threshold,
    }


def evaluate(archive_path: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    cfg = AnalyticsSettings()
    with zipfile.ZipFile(archive_path) as archive:
        registrations = {key(r): r for r in records(archive, "studentRegistration.csv")}
        students = {key(r): r for r in records(archive, "studentInfo.csv")}
        courses = {
            (r["code_module"], r["code_presentation"]): int(r["module_presentation_length"])
            for r in records(archive, "courses.csv")
        }
        assignments: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        assessment_course = {}
        for row in records(archive, "assessments.csv"):
            cid = (row["code_module"], row["code_presentation"])
            assessment_course[row["id_assessment"]] = cid
            if row["date"] and row["assessment_type"] != "Exam":
                due = int(row["date"])
                assignments[cid].append(
                    {
                        "id": row["id_assessment"],
                        "course_id": ":".join(cid),
                        "deadline": ORIGIN + timedelta(days=due),
                        "required": True,
                        "published_at": ORIGIN + timedelta(days=min(0, due)),
                    }
                )
        submissions: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        banked: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        for row in records(archive, "studentAssessment.csv"):
            cid = assessment_course[row["id_assessment"]]
            learner = (*cid, row["id_student"])
            if row["is_banked"] == "1":
                banked[learner].add(row["id_assessment"])
            else:
                submissions[learner].append(
                    {
                        "assignment_id": row["id_assessment"],
                        "student_id": row["id_student"],
                        "course_id": ":".join(cid),
                        "submitted_at": ORIGIN + timedelta(days=int(row["date_submitted"])),
                        "execution_status": "evaluated",
                    }
                )
        # Nine small counters per enrollment, instead of retaining ten million raw observations.
        features: dict[tuple[str, str, str], list[Any]] = {}
        input_rows = 0
        for row in records(archive, "studentVle.csv"):
            input_rows += 1
            day = int(row["date"])
            if day >= max(CUTOFFS):
                continue
            learner = key(row)
            registration = registrations.get(learner)
            if not registration or registration["date_registration"] in {"", "?"}:
                continue
            if day < int(registration["date_registration"]):
                continue
            values = features.setdefault(learner, [0, 0, None, 0, 0, None, 0, 0, None])
            clicks = int(row["sum_click"])
            if clicks <= 0:
                continue
            for i, cutoff in enumerate(CUTOFFS):
                if day < cutoff:
                    values[i * 3 + 2] = (
                        max(day, values[i * 3 + 2]) if values[i * 3 + 2] is not None else day
                    )
                    if day >= cutoff - 7:
                        values[i * 3] += clicks
                    elif day >= cutoff - 14:
                        values[i * 3 + 1] += clicks
        train_ids = {k[2] for k in registrations if k[1].startswith("2013")}
        rows = []
        exclusions: dict[str, int] = defaultdict(int)
        for learner, registration in registrations.items():
            module, presentation, student = learner
            if presentation.startswith("2013"):
                bucket = (
                    int.from_bytes(
                        hashlib.sha256(f"de261-br5:{student}".encode()).digest()[:4], "big"
                    )
                    % 4
                )
                split = "validation_2013" if bucket == 0 else "calibration_2013"
            elif presentation.startswith("2014") and student not in train_ids:
                split = "test_2014_unseen_learners"
            else:
                exclusions["overlapping_or_other_year"] += 1
                continue
            if registration["date_registration"] in {"", "?"}:
                exclusions["missing_registration_date"] += 1
                continue
            enrolled = int(registration["date_registration"])
            withdrawn = (
                int(registration["date_unregistration"])
                if registration["date_unregistration"] not in {"", "?"}
                else None
            )
            if students[learner]["final_result"] == "Withdrawn" and withdrawn is None:
                exclusions["withdrawal_without_date"] += 1
                continue
            course_id = module + ":" + presentation
            for i, cutoff in enumerate(CUTOFFS):
                if enrolled > cutoff - 7 or (withdrawn is not None and withdrawn <= cutoff):
                    continue
                if courses[(module, presentation)] < cutoff + 30:
                    continue
                recent, previous, last = features.get(learner, [0, 0, None] * 3)[i * 3 : i * 3 + 3]
                observed = (
                    []
                    if last is None
                    else [
                        {
                            "student_id": student,
                            "course_id": course_id,
                            "event_time": ORIGIN + timedelta(days=last),
                        }
                    ]
                )
                result = score(
                    {
                        "student_id": student,
                        "course_id": course_id,
                        "status": "active",
                        "enrolled_at": ORIGIN + timedelta(days=enrolled),
                    },
                    {"telemetry_enabled": True},
                    [
                        a
                        for a in assignments[(module, presentation)]
                        if a["id"] not in banked[learner]
                    ],
                    submissions[learner],
                    observed,
                    ORIGIN + timedelta(days=cutoff),
                    recent,
                    previous,
                    cfg,
                )
                label = int(withdrawn is not None and cutoff < withdrawn <= cutoff + 30)
                rows.append(
                    {
                        "student_id": student,
                        "course_id": course_id,
                        "split": split,
                        "cutoff_day": cutoff,
                        "score": result["score"],
                        "inactivity_baseline": int(last is not None and cutoff - last >= 7),
                        "label": label,
                        "lead_days": withdrawn - cutoff
                        if label and withdrawn is not None
                        else None,
                    }
                )
    calibration = [r for r in rows if r["split"] == "calibration_2013"]
    # Fix this decision before inspecting any held-out test metrics. Ties prefer fewer alerts.
    threshold = max(range(10, 101, 5), key=lambda t: (metrics(calibration, "score", t)["f1"], t))
    validation = [r for r in rows if r["split"] == "validation_2013"]
    default = metrics(validation, "score", 60)
    candidate = metrics(validation, "score", threshold)
    promote = candidate["f1"] > default["f1"] and candidate["precision"] >= default["precision"]
    comparisons = []
    for split in ("calibration_2013", "validation_2013", "test_2014_unseen_learners"):
        for evaluation_cutoff in (*CUTOFFS, "all"):
            sample = [
                r
                for r in rows
                if r["split"] == split
                and (evaluation_cutoff == "all" or r["cutoff_day"] == evaluation_cutoff)
            ]
            for name, field, t in [
                ("current_policy", "score", 60),
                ("calibrated_policy", "score", threshold),
                ("inactivity_7d", "inactivity_baseline", 1),
            ]:
                comparisons.append(
                    {
                        "split": split,
                        "cutoff_day": evaluation_cutoff,
                        "method": name,
                        **metrics(sample, field, t),
                    }
                )
    # Keep the per-observation evidence reproducible without publishing raw learner identifiers.
    predictions = [{k: v for k, v in row.items() if k != "student_id"} for row in rows]
    for name, values in [
        ("oulad_predictions.csv", predictions),
        ("oulad_metrics.csv", comparisons),
    ]:
        with (output / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(values)
    report = {
        "dataset": "OULAD",
        "license": "CC BY 4.0",
        "source": (
            "https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset"
        ),
        "archive_sha256": hashlib.file_digest(archive_path.open("rb"), "sha256").hexdigest(),
        "measured_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True)
        ),
        "input_vle_rows": input_rows,
        "observations": len(rows),
        "calibrated_threshold": threshold,
        "excluded_enrollments": dict(exclusions),
        "previously_inspected_2014_results": True,
        "policy_selection": {
            "learner_split": (
                "2013 SHA-256 bucket 0 of 4 for validation; 2014 excludes all 2013 learners"
            ),
            "default_threshold": 60,
            "candidate_threshold": threshold,
            "validation_default": default,
            "validation_candidate": candidate,
            "candidate_meets_promotion_gate": promote,
            "selected_threshold": threshold if promote else 60,
        },
        "metrics": comparisons,
        "limitations": [
            "Daily aggregates, not observed intraday events; sum_click supplies activity weights.",
            (
                "Assessment schedule assumed known at course start; exams without "
                "dates excluded; banked assessments exempt."
            ),
            (
                "All features precede cutoff; target is withdrawal in next 30 days"
                ", not academic failure."
            ),
            (
                "Repeated cutoffs are correlated; pooled metrics are descriptive, "
                "not independent samples."
            ),
            (
                "No causal claim about advisor interventions; no real-world retent"
                "ion improvement measured."
            ),
            "PR-AUC is stepwise average precision with tied scores grouped.",
            "2014 results were inspected in prior runs and are a retrospective evaluation.",
        ],
    }
    (output / "oulad_evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("data/br45-v2/oulad/source.zip"))
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/br45-v2"))
    args = parser.parse_args()
    result = evaluate(args.archive, args.output)
    print(
        json.dumps(
            {k: result[k] for k in ("input_vle_rows", "observations", "calibrated_threshold")},
            indent=2,
        )
    )
