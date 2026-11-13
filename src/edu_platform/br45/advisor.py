"""Course policy and intervention contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from .config import RiskPolicy, settings
from .contracts import timestamp
from .db import Db, state


class PolicyChange(BaseModel):
    expected_version: int = Field(ge=1)
    parameters: RiskPolicy


class CoursePolicy(BaseModel):
    course_id: str
    version: int
    parameters: RiskPolicy
    created_by: str | None = None
    created_at: datetime | None = None
    effective_after: datetime | None = None


class NoteBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    idempotency_key: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=2000)


class Note(BaseModel):
    id: int
    alert_id: str
    actor: str
    action: str
    note: str
    created_at: datetime


def policy(conn: Db, course_id: str) -> dict[str, Any]:
    return conn.execute(
        "SELECT * FROM analytics.course_policies WHERE course_id=%s ORDER BY version DESC LIMIT 1",
        (course_id,),
    ).fetchone() or {
        "course_id": course_id,
        "version": 1,
        "parameters": settings().model_dump(include=set(RiskPolicy.model_fields)),
    }


def change_policy(
    conn: Db, course_id: str, actor: str, change: PolicyChange
) -> dict[str, Any] | None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('br45-cdc-progress'))")
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("br45-policy:" + course_id,))
    current = policy(conn, course_id)
    if current["version"] != change.expected_version:
        return None
    evaluated = state(conn, "evaluation_clock")
    return conn.execute(
        "INSERT INTO analytics.course_policies(course_id,version,parameters,created_by,"
        "effective_after) VALUES(%s,%s,%s,%s,%s) RETURNING *",
        (
            course_id,
            current["version"] + 1,
            Jsonb(change.parameters.model_dump()),
            actor,
            timestamp(evaluated) if evaluated else None,
        ),
    ).fetchone()
