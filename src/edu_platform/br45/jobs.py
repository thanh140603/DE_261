"""Durable assessment requests and fenced publication."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .config import AnalyticsSettings, settings
from .contracts import identity
from .db import Db, connect, state


def active_courses(conn: Db) -> list[str]:
    """Courses with graded source inputs eligible for automatic refresh."""
    return [
        row["course_id"] for row in conn.execute(
            "SELECT DISTINCT data->>'course_id' AS course_id FROM analytics.clean_rows "
            "WHERE table_name='submissions' AND NOT deleted ORDER BY 1"
        )
    ]


def request(
    conn: Db, course: str, start: datetime, end: datetime, cfg: AnalyticsSettings | None = None
) -> dict[str, Any]:
    cfg = cfg or settings()
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    job_id = identity(course, start.isoformat(), end.isoformat())
    row = conn.execute(
        "INSERT INTO analytics.assessment_jobs(id,course_id,window_start,window_end,"
        "requested_revision,engine,required_sequence) VALUES(%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(id) DO UPDATE SET "
        "required_sequence=GREATEST(analytics.assessment_jobs.required_sequence,"
        "excluded.required_sequence), requested_revision=excluded.requested_revision, "
        "engine=excluded.engine, status=CASE "
        "WHEN analytics.assessment_jobs.status='RUNNING' AND "
        "analytics.assessment_jobs.engine=excluded.engine THEN 'RUNNING' "
        "WHEN analytics.assessment_jobs.published_revision=excluded.requested_revision "
        "AND analytics.assessment_jobs.published_engine=excluded.engine THEN 'SUCCEEDED' "
        "ELSE 'PENDING' END RETURNING *",
        (
            job_id,
            course,
            start,
            end,
            state(conn, "assessment_source_revision") or "empty",
            cfg.assessment_engine,
            state(conn, "assessment_sequence") or 0,
        ),
    ).fetchone()
    assert row is not None
    return row


def pending(conn: Db, engine: str, available_sequence: int | None = None) -> dict[str, Any] | None:
    return conn.execute(
        "UPDATE analytics.assessment_jobs SET status='RUNNING',started_at=now(),error=NULL,"
        "lease_generation=lease_generation+1 "
        "WHERE id=(SELECT id FROM analytics.assessment_jobs WHERE engine=%s AND "
        "(status='PENDING' OR (status='RUNNING' AND started_at < now()-interval '30 minutes')) "
        "AND (%s::bigint IS NULL OR required_sequence <= %s) "
        "ORDER BY requested_at,id LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *",
        (engine, available_sequence, available_sequence),
    ).fetchone()


def owns_lease(conn: Db, job: dict[str, Any]) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM analytics.assessment_jobs WHERE id=%s AND status='RUNNING' "
            "AND lease_generation=%s AND started_at >= now()-interval '30 minutes' FOR UPDATE",
            (job["id"], job["lease_generation"]),
        ).fetchone()
        is not None
    )


def complete(
    conn: Db, job: dict[str, Any], revision: str, publication: str, version: int | None = None
) -> None:
    updated = conn.execute(
        "UPDATE analytics.assessment_jobs SET published_revision=%s,completed_at=now(),"
        "publication_id=%s,source_delta_version=%s,published_engine=engine,"
        "status=CASE WHEN requested_revision=%s THEN 'SUCCEEDED' ELSE 'PENDING' END "
        "WHERE id=%s AND status='RUNNING' AND lease_generation=%s AND engine=%s",
        (
            revision, publication, version, revision, job["id"],
            job["lease_generation"], job["engine"],
        ),
    )
    if updated.rowcount != 1:
        raise RuntimeError("Assessment publication lease was lost")


def fail(conn: Db, job: dict[str, Any], error: Exception) -> None:
    conn.execute(
        "UPDATE analytics.assessment_jobs SET status=CASE WHEN requested_revision=%s "
        "THEN 'FAILED' ELSE 'PENDING' END,error=%s WHERE id=%s AND status='RUNNING' "
        "AND lease_generation=%s",
        (job["requested_revision"], str(error)[:2000], job["id"], job["lease_generation"]),
    )


def process_postgres(cfg: AnalyticsSettings) -> None:
    from .assessment import refresh

    with connect() as conn:
        job = pending(conn, "postgres")
    if job is None:
        return
    try:
        with connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('br45-cdc-progress'))")
            if not owns_lease(conn, job):
                return
            revision = state(conn, "assessment_source_revision") or "empty"
            refresh(conn, job["window_start"], job["window_end"], job["course_id"], cfg)
            complete(conn, job, revision, identity(job["id"], "postgres", revision))
    except Exception as exc:
        with connect() as conn:
            fail(conn, job, exc)
