"""Explainable BR5 policy and alert lifecycle. Scores are points, not probabilities."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from .config import AnalyticsSettings, settings
from .contracts import identity, timestamp
from .db import Db, clean, state


def score(
    enrollment: dict[str, Any],
    course: dict[str, Any],
    assignments: list[dict[str, Any]],
    submissions: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    evaluated_at: datetime,
    recent: int,
    previous: int,
    cfg: AnalyticsSettings | None = None,
) -> dict[str, Any]:
    cfg = cfg or settings()
    enrolled = timestamp(enrollment["enrolled_at"])
    sid, cid = enrollment["student_id"], enrollment["course_id"]
    eligible = enrollment["status"] == "active" and evaluated_at - enrolled >= timedelta(days=7)
    due = [
        a
        for a in assignments
        if a["course_id"] == cid
        and a["required"]
        and a.get("deadline")
        and enrolled <= timestamp(a["deadline"]) < evaluated_at
        and timestamp(a["deadline"]) >= evaluated_at - timedelta(days=14)
        and timestamp(a["published_at"]) <= timestamp(a["deadline"])
    ]
    submitted = {
        s["assignment_id"]
        for s in submissions
        if s["student_id"] == sid
        and s["course_id"] == cid
        and enrolled <= timestamp(s["submitted_at"]) < evaluated_at
        and s["execution_status"] != "infra_error"
    }
    missed = sum(a["id"] not in submitted for a in due)
    completion = (len(due) - missed) / len(due) if due else None
    observed = [
        timestamp(a["event_time"])
        for a in activities
        if a["student_id"] == sid
        and a["course_id"] == cid
        and enrolled <= timestamp(a["event_time"]) < evaluated_at
    ]
    last = max(observed) if observed else None
    telemetry = bool(course["telemetry_enabled"])
    # A provisioned telemetry path alone is not evidence the learner ever used it.
    inactivity_days = (evaluated_at - last).total_seconds() / 86400 if last else None
    decline = 1 - recent / previous if previous >= 3 else None
    reasons: list[dict[str, Any]] = []
    if eligible:
        if telemetry and last and inactivity_days is not None and inactivity_days >= 7:
            reasons.append(
                {
                    "signal": "inactivity",
                    "points": cfg.inactivity_points,
                    "reason": "No meaningful learning activity for at least 7 days",
                }
            )
        if missed:
            reasons.append(
                {
                    "signal": "missed_deadlines",
                    "points": cfg.missed_points,
                    "reason": (
                        f"{missed} required assignments remain unsubmitted after their deadlines"
                    ),
                }
            )
        if completion is not None and completion < 0.5:
            reasons.append(
                {
                    "signal": "low_completion",
                    "points": cfg.completion_points,
                    "reason": (
                        f"Recent due-assignment submission rate {completion:.0%} is below 50%"
                    ),
                }
            )
        if telemetry and decline is not None and decline >= 0.5:
            reasons.append(
                {
                    "signal": "activity_decline",
                    "points": cfg.decline_points,
                    "reason": (
                        "Learning activity decreased by "
                        f"{decline:.0%}"
                        " from the preceding 7-day window"
                    ),
                }
            )
    points = min(100, sum(r["points"] for r in reasons))
    level = (
        "CRITICAL"
        if points >= cfg.critical_threshold
        else "HIGH"
        if points >= cfg.high_threshold
        else "MEDIUM"
        if points >= cfg.medium_threshold
        else "LOW"
    )
    return {
        "student_id": sid,
        "course_id": cid,
        "score": points,
        "level": level,
        "eligible": eligible,
        "eligibility_reason": "At least 7 days of active enrollment"
        if eligible
        else "Inactive enrollment or fewer than 7 days of history",
        "evaluated_at": evaluated_at.isoformat(),
        "reasons": reasons,
        "features": {
            "activity_7d": max(0, recent),
            "activity_previous_7d": max(0, previous),
            "activity_14d": max(0, recent + previous),
            "last_activity_at": last.isoformat() if last else None,
            "inactivity_days": inactivity_days,
            "due_assignments_14d": len(due),
            "missed_deadlines_14d": missed,
            "submission_rate_14d": completion,
            "activity_decline": decline,
            "telemetry_available": telemetry,
        },
        "policy": {
            "alert_threshold": cfg.alert_threshold,
            "window_days": 7,
            "slide_seconds": cfg.slide_seconds,
            "allowed_lateness_days": cfg.lateness_days,
            "minimum_reference_events": 3,
        },
    }


def persist(conn: Db, result: dict[str, Any], cfg: AnalyticsSettings | None = None) -> None:
    cfg = cfg or settings()
    sid, cid = result["student_id"], result["course_id"]
    evaluated = timestamp(result["evaluated_at"])
    # Serializes API alert actions and processor updates for a single learner/course.
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (sid + ":" + cid,))
    old = conn.execute(
        "SELECT * FROM analytics.risk_state WHERE student_id=%s AND course_id=%s FOR UPDATE",
        (sid, cid),
    ).fetchone()
    if old and old["evaluated_at"] > evaluated:
        return
    conn.execute(
        (
            "INSERT INTO analytics.risk_state(student_id,course_id,score,level,eligible,e"
            "valuated_at,data) VALUES(%s,%s,%s,%s,%s,%s,%s) ON "
            "CONFLICT(student_id,course_id) DO UPDATE SET score=excluded.score,level=excl"
            "uded.level,eligible=excluded.eligible,evaluated_at=excluded.evaluated_at,dat"
            "a=excluded.data,computed_at=now()"
        ),
        (sid, cid, result["score"], result["level"], result["eligible"], evaluated, Jsonb(result)),
    )
    conn.execute(
        (
            "INSERT INTO "
            "analytics.risk_history(id,student_id,course_id,evaluated_at,score,data) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING"
        ),
        (identity(result), sid, cid, evaluated, result["score"], Jsonb(result)),
    )
    alert = conn.execute(
        (
            "SELECT * FROM analytics.dropout_alerts WHERE student_id=%s AND course_id=%s "
            "AND status<>'RESOLVED' FOR UPDATE"
        ),
        (sid, cid),
    ).fetchone()
    qualifies = result["eligible"] and result["score"] >= cfg.alert_threshold
    if not qualifies:
        if alert:
            conn.execute(
                (
                    "UPDATE analytics.dropout_alerts SET "
                    "status='RESOLVED',resolved_at=now(),resolved_by='system:risk-recovery' WHERE"
                    " id=%s"
                ),
                (alert["id"],),
            )
        return
    if alert:
        conn.execute(
            (
                "UPDATE analytics.dropout_alerts SET "
                "score=%s,level=%s,reasons=%s,evaluated_at=%s WHERE id=%s"
            ),
            (result["score"], result["level"], Jsonb(result["reasons"]), evaluated, alert["id"]),
        )
        return
    previous = conn.execute(
        (
            "SELECT evaluated_at FROM analytics.dropout_alerts WHERE student_id=%s AND "
            "course_id=%s ORDER BY created_at DESC LIMIT 1"
        ),
        (sid, cid),
    ).fetchone()
    crossing = not old or not old["eligible"] or old["score"] < cfg.alert_threshold
    worsening = old and result["score"] - old["score"] >= 20
    cooled = not previous or evaluated - previous["evaluated_at"] >= timedelta(
        hours=cfg.cooldown_hours
    )
    if (crossing or worsening) and cooled:
        conn.execute(
            (
                "INSERT INTO analytics.dropout_alerts(id,student_id,course_id,score,level,rea"
                "sons,status,evaluated_at) VALUES(%s,%s,%s,%s,%s,%s,'NEW',%s) ON CONFLICT DO "
                "NOTHING"
            ),
            (
                identity(sid, cid, result["evaluated_at"], "alert"),
                sid,
                cid,
                result["score"],
                result["level"],
                Jsonb(result["reasons"]),
                evaluated,
            ),
        )


def refresh(conn: Db, evaluated: datetime, cfg: AnalyticsSettings | None = None) -> int:
    cfg = cfg or settings()
    courses = {c["id"]: c for c in clean(conn, "courses")}
    assignments, submissions, activities = (
        clean(conn, t) for t in ("assignments", "submissions", "activity_events")
    )
    count = 0
    enrollments = clean(conn, "enrollments")
    live = {(e["student_id"], e["course_id"]) for e in enrollments if e["course_id"] in courses}
    for old in conn.execute("SELECT data FROM analytics.risk_state"):
        data = old["data"]
        if (data["student_id"], data["course_id"]) not in live:
            retired = {
                **data,
                "score": 0,
                "level": "LOW",
                "eligible": False,
                "eligibility_reason": "Enrollment or course no longer exists",
                "evaluated_at": evaluated.isoformat(),
                "reasons": [],
            }
            persist(conn, retired, cfg)
    for en in enrollments:
        if en["course_id"] not in courses or timestamp(en["enrolled_at"]) > evaluated:
            continue
        counts = {}
        for at in (evaluated, evaluated - timedelta(days=7)):
            row = conn.execute(
                (
                    "SELECT activity_count FROM analytics.activity_windows WHERE student_id=%s "
                    "AND course_id=%s AND window_end=%s"
                ),
                (en["student_id"], en["course_id"], at),
            ).fetchone()
            counts[at] = row["activity_count"] if row else 0
        result = score(
            en,
            courses[en["course_id"]],
            assignments,
            submissions,
            activities,
            evaluated,
            counts[evaluated],
            counts[evaluated - timedelta(days=7)],
            cfg,
        )
        persist(conn, result, cfg)
        count += 1
    state(
        conn,
        "risk_refresh",
        {
            "evaluated_at": evaluated.isoformat(),
            "students": count,
            "success_at": datetime.now(evaluated.tzinfo).isoformat(),
        },
    )
    return count
