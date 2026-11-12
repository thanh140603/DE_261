"""BR45 dashboard contracts backed by the opt-in synthetic replay."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from hmac import compare_digest
from statistics import mean
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import AwareDatetime, BaseModel, Field

from .api import (
    AlertStatus,
    AnomalyState,
    Limit,
    Offset,
    Principal,
    RiskLevel,
    Severity,
    bearer,
    paged,
    scope,
)
from .contracts import timestamp
from .db import ROOT
from .outputs import Alert, Metric, Page, Risk, RiskPage, StudentRisk
from .replay import COURSES, Replay, assessment_rows

router = APIRouter(tags=["BR4 / BR5 simulated replay"])


async def principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials:
        for role in ("instructor", "advisor"):
            if compare_digest(credentials.credentials.encode(), f"{role}-demo".encode()):
                return Principal(f"{role}-local", role, list(COURSES))
    detail = (
        "Invalid analytics access token" if credentials else "An analytics access token is required"
    )
    raise HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


User = Annotated[Principal, Depends(principal)]


async def instructor(user: User) -> Principal:
    if user.role != "instructor":
        raise HTTPException(403, "Instructor access required")
    return user


async def advisor(user: User) -> Principal:
    if user.role != "advisor":
        raise HTTPException(403, "Advisor access required")
    return user


async def replay(request: Request) -> Replay:
    engine: Replay = request.app.state.br45_replay
    engine.tick()
    return engine


Instructor = Annotated[Principal, Depends(instructor)]
Advisor = Annotated[Principal, Depends(advisor)]
Engine = Annotated[Replay, Depends(replay)]


class Advance(BaseModel):
    revision: int = Field(ge=0)


@router.get("/analytics/session")
async def session(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "role": user.role,
        "replay": True,
        "courses": [{"id": course.id, "title": course.title} for course in COURSES.values()],
    }


@router.get("/analytics/replay")
async def replay_status(engine: Engine, user: User) -> dict[str, Any]:
    return engine.status()


@router.post("/analytics/replay/advance")
async def advance(body: Advance, engine: Engine, user: User) -> dict[str, Any]:
    engine.tick(body.revision)
    return engine.status()


@lru_cache(maxsize=1)
def benchmark_results() -> dict[str, Any]:
    evidence = ROOT / "docs/evidence/br45"

    def summarize(filename: str, size: str, measures: tuple[str, ...]) -> list[dict[str, Any]]:
        groups: dict[int, list[dict[str, str]]] = {}
        with (evidence / filename).open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                groups.setdefault(int(row[size]), []).append(row)
        return [
            {
                "records": count,
                "runs": len(rows),
                "correct_runs": sum(row["correct"].lower() == "true" for row in rows),
                **{measure: mean(float(row[measure]) for row in rows) for measure in measures},
            }
            for count, rows in sorted(groups.items())
        ]

    cdc = json.loads((evidence / "final_e2e_result.json").read_text(encoding="utf-8"))
    comparison = evidence / "engine_comparison.json"
    return {
        "engine_comparison": json.loads(comparison.read_text(encoding="utf-8"))
        if comparison.is_file()
        else None,
        "br4": summarize(
            "br4_benchmark.csv",
            "evaluation_rows",
            (
                "sql_ms",
                "python_ms",
                "persisted_refresh_ms",
                "query_ms",
                "correction_refresh_ms",
            ),
        ),
        "br5": summarize(
            "br5_stream_benchmark.csv",
            "unique_events",
            (
                "kafka_to_persisted_windows_ms",
                "unique_events_per_second",
                "python_batch_ms",
            ),
        ),
        "cdc_to_alert_ms": cdc["cdc_to_alert_ms"],
        "cdc_measured_at": cdc["measured_at"],
    }


@router.get("/analytics/replay/benchmarks")
async def benchmarks(user: User) -> dict[str, Any]:
    try:
        return benchmark_results()
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Measured benchmark evidence is unavailable") from exc


def assessment(
    engine: Replay,
    course: str,
    start: datetime | None,
    end: datetime | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime, datetime]:
    end = end or engine.at
    start = start or end - timedelta(days=30)
    if not timedelta(0) < end - start <= timedelta(days=366):
        raise HTTPException(422, "Use timezone-aware dates with 0 < end-start <= 366 days")
    questions, cases = assessment_rows(
        COURSES[course], engine.stage, engine.anchor, engine.at, start, end
    )
    return questions, cases, start, end


def metric_order(row: dict[str, Any]) -> tuple[bool, float, str]:
    return row["pass_rate"] is None, row["pass_rate"] or 0, row["id"]


@router.get("/instructor/courses/{course_id}/questions/statistics", response_model=Page[Metric])
async def questions(
    course_id: str,
    engine: Engine,
    user: Instructor,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    assignment_id: str | None = None,
    status: AnomalyState | None = None,
    severity: Severity | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
    sort: Literal["pass_rate", "students", "question"] = "pass_rate",
) -> dict[str, Any]:
    scope(user, course_id)
    rows, _, first, last = assessment(engine, course_id, start, end)
    order: Callable[[dict[str, Any]], Any] = {
        "pass_rate": metric_order,
        "students": lambda row: (-row["unique_students"], row["id"]),
        "question": lambda row: row["question_id"],
    }[sort]
    filtered = [
        row
        for row in rows
        if (assignment_id is None or row["assignment_id"] == assignment_id)
        and (status is None or row["state"] == status)
        and (severity is None or row["severity"] == severity)
    ]
    return paged(sorted(filtered, key=order), offset, limit) | {
        "window_start": first,
        "window_end": last,
    }


@router.get("/instructor/questions/{question_id}/test-cases", response_model=Page[Metric])
@router.get("/instructor/questions/{question_id}/statistics", response_model=Page[Metric])
async def question_detail(
    question_id: str,
    request: Request,
    engine: Engine,
    user: Instructor,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    version: Annotated[int | None, Query(ge=1)] = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> dict[str, Any]:
    course, _, suffix = question_id.partition("-replay-q")
    if course not in COURSES or suffix not in {"1", "2", "3"}:
        raise HTTPException(404, "Question not found")
    scope(user, course)
    questions, cases, first, last = assessment(engine, course, start, end)
    rows = cases if request.url.path.endswith("/test-cases") else questions
    filtered = [
        row
        for row in rows
        if row["question_id"] == question_id
        and (version is None or row["question_version"] == version)
    ]
    return paged(sorted(filtered, key=metric_order), offset, limit) | {
        "window_start": first,
        "window_end": last,
    }


def in_range(value: str, start: datetime | None, end: datetime | None) -> bool:
    at = timestamp(value)
    return (start is None or start <= at) and (end is None or at < end)


@router.get("/advisor/courses/{course_id}/at-risk-students", response_model=RiskPage)
async def learners(
    course_id: str,
    engine: Engine,
    user: Advisor,
    level: RiskLevel | None = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> dict[str, Any]:
    scope(user, course_id)
    rows = engine.risks[course_id]
    levels = {
        key: sum(row["level"] == key for row in rows)
        for key in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    }
    filtered = [
        row
        for row in rows
        if (level is None or row["level"] == level) and in_range(row["evaluated_at"], start, end)
    ]
    return paged(filtered, offset, limit) | {"summary": {"monitored": len(rows), "levels": levels}}


@router.get("/advisor/students/{student_id}/risk", response_model=StudentRisk)
async def student(
    student_id: str,
    engine: Engine,
    user: Advisor,
    course_id: str | None = None,
) -> dict[str, Any]:
    if course_id:
        scope(user, course_id)
    history = engine.history.get(student_id)
    if history:
        current = history[0]
        if current["course_id"] in user.courses and (
            not course_id or course_id == current["course_id"]
        ):
            return {"student_id": student_id, "courses": [current]}
    raise HTTPException(404, "Student risk not found in your scope")


@router.get("/advisor/students/{student_id}/risk-history", response_model=Page[Risk])
async def risk_history(
    student_id: str,
    engine: Engine,
    user: Advisor,
    course_id: str | None = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> dict[str, Any]:
    if course_id:
        scope(user, course_id)
    rows = [
        row
        for row in engine.history.get(student_id, [])
        if row["course_id"] in user.courses
        and (not course_id or row["course_id"] == course_id)
        and in_range(row["evaluated_at"], start, end)
    ]
    return paged(rows, offset, limit)


@router.get("/advisor/alerts", response_model=Page[Alert])
async def alerts(
    engine: Engine,
    user: Advisor,
    course_id: str | None = None,
    level: RiskLevel | None = None,
    status: AlertStatus | None = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> dict[str, Any]:
    if course_id:
        scope(user, course_id)
    rows = [
        row
        for row in engine.alerts.values()
        if row["course_id"] in user.courses
        and (not course_id or row["course_id"] == course_id)
        and (level is None or row["level"] == level)
        and (status is None or row["status"] == status)
        and in_range(row["created_at"], start, end)
    ]
    return paged(sorted(rows, key=lambda row: (-row["score"], row["id"])), offset, limit)


@router.patch("/advisor/alerts/{alert_id}/{action}", response_model=Alert)
async def update_alert(
    alert_id: str,
    action: Literal["acknowledge", "resolve"],
    engine: Engine,
    user: Advisor,
) -> dict[str, Any]:
    alert = engine.alerts.get(alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    scope(user, alert["course_id"])
    if action == "acknowledge" and alert["status"] == "RESOLVED":
        raise HTTPException(409, "A resolved alert cannot be acknowledged")
    engine.update_alert(
        alert,
        "ACKNOWLEDGED" if action == "acknowledge" else "RESOLVED",
        datetime.now(UTC).isoformat(),
    )
    return alert
