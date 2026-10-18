"""Scoped persistent BR4/BR5 APIs. FastAPI publishes these contracts at /docs."""

from __future__ import annotations

import hmac
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, BaseModel, Field

from .assessment import refresh as refresh_assessments
from .config import settings
from .contracts import timestamp
from .db import Db, clean, connect, state
from .outputs import Alert, Metric, Page, Risk, RiskPage, StudentRisk

router = APIRouter(tags=["BR4 / BR5 persistent analytics"])
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    id: str
    role: str
    courses: list[str]


def principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None:
        raise HTTPException(
            401, "An analytics access token is required", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        accounts = json.loads(settings().auth)
    except ValueError as exc:
        raise HTTPException(503, "Analytics authentication is not configured") from exc
    for token, account in accounts.items():
        if hmac.compare_digest(token, credentials.credentials):
            return Principal(account["id"], account["role"], account["courses"])
    raise HTTPException(
        401, "Invalid analytics access token", headers={"WWW-Authenticate": "Bearer"}
    )


def instructor(user: Annotated[Principal, Depends(principal)]) -> Principal:
    if user.role != "instructor":
        raise HTTPException(403, "Instructor access required")
    return user


def advisor(user: Annotated[Principal, Depends(principal)]) -> Principal:
    if user.role != "advisor":
        raise HTTPException(403, "Advisor access required")
    return user


def database() -> Iterator[Db]:
    try:
        with connect() as conn:
            yield conn
    except psycopg.OperationalError as exc:
        raise HTTPException(
            503, "Analytical storage is unavailable; retry after the BR4/BR5 services recover"
        ) from exc
    except psycopg.errors.UndefinedTable as exc:
        raise HTTPException(503, "BR4/BR5 migration has not been applied") from exc


DB = Annotated[Db, Depends(database)]
Instructor = Annotated[Principal, Depends(instructor)]
Advisor = Annotated[Principal, Depends(advisor)]
User = Annotated[Principal, Depends(principal)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
AnomalyState = Literal[
    "NORMAL", "INSUFFICIENT_DATA", "LOW_PASS_RATE", "SUSPICIOUS_TEST_CASE", "NEEDS_REVIEW"
]
Severity = Literal["INFO", "MEDIUM", "HIGH"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
AlertStatus = Literal["NEW", "ACKNOWLEDGED", "RESOLVED"]


def scope(user: Principal, course_id: str) -> None:
    if course_id not in user.courses:
        raise HTTPException(403, "Course is outside your authorized scope")


def window(conn: Db, start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    end = end or timestamp(state(conn, "evaluation_clock") or datetime.now(UTC).isoformat())
    start = start or end - timedelta(days=30)
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or end <= start
        or end - start > timedelta(days=366)
    ):
        raise HTTPException(422, "Use timezone-aware dates with 0 < end-start <= 366 days")
    return start, end


def paged(items: list[Any], offset: int, limit: int) -> dict[str, Any]:
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "offset": offset,
        "limit": limit,
    }


@router.get("/analytics/session")
def session(conn: DB, user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "role": user.role,
        "courses": [c for c in clean(conn, "courses") if c["id"] in user.courses],
    }


@router.get("/analytics/diagnostics")
def diagnostics(conn: DB, user: User) -> dict[str, Any]:
    if user.role not in {"instructor", "advisor"}:
        raise HTTPException(403, "Staff access required")
    return {
        "state": list(
            conn.execute("SELECT key,value,updated_at FROM analytics.pipeline_state ORDER BY key")
        ),
        "raw_changes": (
            conn.execute("SELECT count(*) n FROM analytics.raw_changes").fetchone() or {}
        )["n"],
        "invalid_records": (
            conn.execute("SELECT count(*) n FROM analytics.quarantine").fetchone() or {}
        )["n"],
        "outbox_pending": (
            conn.execute(
                "SELECT count(*) n FROM analytics.outbox WHERE published_at IS NULL"
            ).fetchone()
            or {}
        )["n"],
    }


def question_scope(conn: Db, user: Principal, question_id: str) -> str:
    result = conn.execute(
        (
            "SELECT a.data->>'course_id' course_id FROM analytics.clean_rows q JOIN "
            "analytics.clean_rows a ON a.table_name='assignments' AND "
            "a.data->>'id'=q.data->>'assignment_id' AND NOT a.deleted WHERE "
            "q.table_name='questions' AND q.data->>'id'=%s AND NOT q.deleted LIMIT 1"
        ),
        (question_id,),
    ).fetchone()
    if not result:
        raise HTTPException(404, "Question not found")
    scope(user, result["course_id"])
    return str(result["course_id"])


def assessment_rows(
    conn: Db,
    user: Principal,
    course_id: str,
    kind: str,
    start: Any,
    end: Any,
    assignment_id: Any = None,
    status: Any = None,
    severity: Any = None,
    question_id: Any = None,
    version: Any = None,
    offset: Any = 0,
    limit: Any = 50,
    sort: Any = "pass_rate",
) -> dict[str, Any]:
    scope(user, course_id)
    start, end = window(conn, start, end)
    # Requests for arbitrary windows materialize real SQL results in the same persisted marts.
    refresh_assessments(conn, start, end, course_id)
    tables = {
        "questions": "mart_question_pass_statistics",
        "cases": "mart_test_case_pass_statistics",
        "anomalies": "mart_question_anomalies",
    }
    order = {
        "pass_rate": "(data->>'pass_rate')::float ASC NULLS LAST,id",
        "students": "(data->>'unique_students')::int DESC,id",
        "question": "question_id,id",
    }[sort]
    params = {
        "course": course_id,
        "start": start,
        "end": end,
        "assignment": assignment_id,
        "status": status,
        "severity": severity,
        "question": question_id,
        "version": version,
    }
    where = (
        "course_id=%(course)s AND window_start=%(start)s AND window_end=%(end)s AND "
        "(%(assignment)s::text IS NULL OR assignment_id=%(assignment)s) AND "
        "(%(status)s::text IS NULL OR data->>'state'=%(status)s) AND "
        "(%(severity)s::text IS NULL OR data->>'severity'=%(severity)s) AND "
        "(%(question)s::text IS NULL OR question_id=%(question)s) AND "
        "(%(version)s::int IS NULL OR (data->>'question_version')::int=%(version)s)"
    )
    total = (
        conn.execute(
            f"SELECT count(*) n FROM analytics.{tables[kind]} WHERE {where}", params
        ).fetchone()
        or {}
    )["n"]
    items = [
        r["data"]
        for r in conn.execute(
            (
                "SELECT data FROM analytics."
                f"{tables[kind]}"
                " WHERE "
                f"{where}"
                " ORDER BY "
                f"{order}"
                " LIMIT %(limit)s OFFSET %(offset)s"
            ),
            {**params, "limit": limit, "offset": offset},
        )
    ]
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "window_start": start,
        "window_end": end,
    }


@router.get("/instructor/courses/{course_id}/questions/statistics", response_model=Page[Metric])
def questions(
    course_id: str,
    conn: DB,
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
    return assessment_rows(
        conn,
        user,
        course_id,
        "questions",
        start,
        end,
        assignment_id,
        status,
        severity,
        offset=offset,
        limit=limit,
        sort=sort,
    )


@router.get("/instructor/questions/{question_id}/statistics", response_model=Page[Metric])
def question(
    question_id: str,
    conn: DB,
    user: Instructor,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    version: Annotated[int | None, Query(ge=1)] = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> dict[str, Any]:
    return assessment_rows(
        conn,
        user,
        question_scope(conn, user, question_id),
        "questions",
        start,
        end,
        question_id=question_id,
        version=version,
        offset=offset,
        limit=limit,
    )


@router.get("/instructor/questions/{question_id}/test-cases", response_model=Page[Metric])
def test_cases(
    question_id: str,
    conn: DB,
    user: Instructor,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    version: Annotated[int | None, Query(ge=1)] = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> dict[str, Any]:
    return assessment_rows(
        conn,
        user,
        question_scope(conn, user, question_id),
        "cases",
        start,
        end,
        question_id=question_id,
        version=version,
        offset=offset,
        limit=limit,
    )


@router.get("/instructor/courses/{course_id}/anomalies", response_model=Page[Metric])
def anomalies(
    course_id: str,
    conn: DB,
    user: Instructor,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    assignment_id: str | None = None,
    status: AnomalyState | None = None,
    severity: Severity | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> dict[str, Any]:
    return assessment_rows(
        conn,
        user,
        course_id,
        "anomalies",
        start,
        end,
        assignment_id,
        status,
        severity,
        offset=offset,
        limit=limit,
    )


@router.get("/instructor/anomalies/{anomaly_id}", response_model=Metric)
def anomaly(anomaly_id: str, conn: DB, user: Instructor) -> dict[str, Any]:
    row = conn.execute(
        "SELECT data,course_id FROM analytics.mart_question_anomalies WHERE id=%s", (anomaly_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Anomaly not found")
    scope(user, row["course_id"])
    return cast(dict[str, Any], row["data"])


def risk_rows(
    conn: Db,
    user: Principal,
    course_id: Any = None,
    student_id: Any = None,
    level: Any = None,
    start: Any = None,
    end: Any = None,
) -> list[dict[str, Any]]:
    if course_id:
        scope(user, course_id)
    active = {
        (e["student_id"], e["course_id"])
        for e in clean(conn, "enrollments")
        if e["status"] == "active"
    }
    return [
        r["data"] | {"computed_at": r["computed_at"].isoformat()}
        for r in conn.execute(
            (
                "SELECT data,computed_at FROM analytics.risk_state WHERE course_id=ANY(%s) "
                "AND (%s::text IS NULL OR course_id=%s) AND (%s::text IS NULL OR "
                "student_id=%s) AND (%s::text IS NULL OR level=%s) AND (%s::timestamptz IS "
                "NULL OR evaluated_at >= %s) AND (%s::timestamptz IS NULL OR evaluated_at < "
                "%s) ORDER BY score DESC,student_id,course_id"
            ),
            (
                user.courses,
                course_id,
                course_id,
                student_id,
                student_id,
                level,
                level,
                start,
                start,
                end,
                end,
            ),
        )
        if (r["data"]["student_id"], r["data"]["course_id"]) in active
    ]


@router.get("/advisor/courses/{course_id}/at-risk-students", response_model=RiskPage)
def at_risk(
    course_id: str,
    conn: DB,
    user: Advisor,
    level: RiskLevel | None = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> dict[str, Any]:
    all_rows = risk_rows(conn, user, course_id)
    return {
        **paged(risk_rows(conn, user, course_id, level=level, start=start, end=end), offset, limit),
        "summary": {
            "monitored": len(all_rows),
            "levels": {
                v: sum(r["level"] == v for r in all_rows)
                for v in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
            },
        },
    }


@router.get("/advisor/students/{student_id}/risk", response_model=StudentRisk)
def student_risk(
    student_id: str, conn: DB, user: Advisor, course_id: str | None = None
) -> dict[str, Any]:
    rows = risk_rows(conn, user, course_id, student_id)
    if not rows:
        raise HTTPException(404, "Student risk not found in your scope")
    return {"student_id": student_id, "courses": rows}


@router.get("/advisor/students/{student_id}/risk-history", response_model=Page[Risk])
def risk_history(
    student_id: str,
    conn: DB,
    user: Advisor,
    course_id: str | None = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> dict[str, Any]:
    if course_id:
        scope(user, course_id)
    params = (student_id, user.courses, course_id, course_id, start, start, end, end)
    where = (
        "student_id=%s AND course_id=ANY(%s) AND (%s::text IS NULL OR course_id=%s) "
        "AND (%s::timestamptz IS NULL OR evaluated_at >= %s) AND (%s::timestamptz IS "
        "NULL OR evaluated_at < %s)"
    )
    total = (
        conn.execute(
            f"SELECT count(*) n FROM analytics.risk_history WHERE {where}", params
        ).fetchone()
        or {}
    )["n"]
    rows = [
        r["data"]
        for r in conn.execute(
            (
                "SELECT data FROM analytics.risk_history WHERE "
                f"{where}"
                " ORDER BY evaluated_at DESC,recorded_at DESC,id LIMIT %s OFFSET %s"
            ),
            (*params, limit, offset),
        )
    ]
    return {"items": rows, "total": total, "offset": offset, "limit": limit}


@router.get("/advisor/alerts", response_model=Page[Alert])
def alerts(
    conn: DB,
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
    params = (
        user.courses,
        course_id,
        course_id,
        level,
        level,
        status,
        status,
        start,
        start,
        end,
        end,
    )
    where = (
        "course_id=ANY(%s) AND (%s::text IS NULL OR course_id=%s) AND (%s::text IS "
        "NULL OR level=%s) AND (%s::text IS NULL OR status=%s) AND (%s::timestamptz "
        "IS NULL OR created_at >= %s) AND (%s::timestamptz IS NULL OR created_at < "
        "%s)"
    )
    total = (
        conn.execute(
            f"SELECT count(*) n FROM analytics.dropout_alerts WHERE {where}", params
        ).fetchone()
        or {}
    )["n"]
    rows = list(
        conn.execute(
            (
                "SELECT * FROM analytics.dropout_alerts WHERE "
                f"{where}"
                " ORDER BY score DESC,created_at DESC,id LIMIT %s OFFSET %s"
            ),
            (*params, limit, offset),
        )
    )
    return {"items": rows, "total": total, "offset": offset, "limit": limit}


def update_alert(conn: Db, user: Principal, alert_id: str, target: str) -> dict[str, Any]:
    found = conn.execute(
        "SELECT * FROM analytics.dropout_alerts WHERE id=%s", (alert_id,)
    ).fetchone()
    if not found:
        raise HTTPException(404, "Alert not found")
    scope(user, found["course_id"])
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (found["student_id"] + ":" + found["course_id"],),
    )
    current = conn.execute(
        "SELECT * FROM analytics.dropout_alerts WHERE id=%s FOR UPDATE", (alert_id,)
    ).fetchone()
    assert current is not None
    if target == "ACKNOWLEDGED" and current["status"] == "RESOLVED":
        raise HTTPException(409, "A resolved alert cannot be acknowledged")
    column = "acknowledged" if target == "ACKNOWLEDGED" else "resolved"
    updated = conn.execute(
        (
            "UPDATE analytics.dropout_alerts SET status=%s,"
            f"{column}"
            "_at=coalesce("
            f"{column}"
            "_at,now()),"
            f"{column}"
            "_by=coalesce("
            f"{column}"
            "_by,%s) WHERE id=%s RETURNING *"
        ),
        (target, user.id, alert_id),
    ).fetchone()
    assert updated is not None
    return updated


@router.patch("/advisor/alerts/{alert_id}/acknowledge", response_model=Alert)
def acknowledge(alert_id: str, conn: DB, user: Advisor) -> dict[str, Any]:
    return update_alert(conn, user, alert_id, "ACKNOWLEDGED")


@router.patch("/advisor/alerts/{alert_id}/resolve", response_model=Alert)
def resolve(alert_id: str, conn: DB, user: Advisor) -> dict[str, Any]:
    return update_alert(conn, user, alert_id, "RESOLVED")


class ActivityBody(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    course_id: str = Field(min_length=1, max_length=200)
    event_type: Literal["lesson_view", "lesson_complete", "submission", "session"]
    event_time: AwareDatetime


@router.post("/learning/activity", status_code=202)
def activity(body: ActivityBody, conn: DB, user: User) -> dict[str, Any]:
    if user.role != "learner":
        raise HTTPException(403, "Learner access required")
    scope(user, body.course_id)
    if body.event_time > datetime.now(UTC) + timedelta(minutes=5):
        raise HTTPException(422, "Activity timestamp is in the future")
    enrollment = conn.execute(
        "SELECT 1 FROM br45.enrollments WHERE student_id=%s AND course_id=%s AND status='active'",
        (user.id, body.course_id),
    ).fetchone()
    if not enrollment:
        raise HTTPException(403, "Active enrollment required")
    existing = conn.execute(
        "SELECT * FROM br45.activity_events WHERE id=%s", (body.event_id,)
    ).fetchone()
    if existing and (existing["student_id"] != user.id or existing["course_id"] != body.course_id):
        raise HTTPException(409, "Activity identifier is already in use")
    conn.execute(
        (
            "INSERT INTO "
            "br45.activity_events(id,student_id,course_id,event_type,event_time) "
            "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING"
        ),
        (body.event_id, user.id, body.course_id, body.event_type, body.event_time),
    )
    return {"event_id": body.event_id, "status": "persisted_in_oltp"}
