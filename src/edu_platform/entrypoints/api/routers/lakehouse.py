"""Scoped BR6/BR7/BR8 APIs over the lakehouse marts (read through Trino, ADR 0010).

Same bearer tokens as the BR4/BR5 APIs (EDU_BR45_AUTH). Scopes:
- admin       organisations[]  -> BR6 org progress (k-anonymous mart, never un-suppressed)
- instructor  courses[]        -> BR7 video heatmaps, BR8 engagement trends of those courses
The demo endpoints (/admin/organisations/{id}/progress, /instructor/videos/...) are untouched.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from edu_platform.br45.api import Principal, instructor, principal
from edu_platform.contexts.analytics.application.ports import (
    AnalyticsMartReader,
    LiveOverlayReader,
    VideoVersion,
)
from edu_platform.contexts.analytics.infrastructure.cached_mart_reader import CachedMartReader
from edu_platform.contexts.analytics.infrastructure.redis_live_overlay import RedisLiveOverlay
from edu_platform.contexts.analytics.infrastructure.trino_mart_reader import (
    TrinoMartReader,
    trino_query,
)
from edu_platform.platform.config import get_settings
from edu_platform.platform.logging import get_logger
from edu_platform.platform.storage.redis_client import create_redis_client

router = APIRouter(tags=["BR6 / BR7 / BR8 lakehouse analytics"])
log = get_logger(__name__)
LIVE_MAX_DAYS = 7  # overlay at most a week past the mart snapshot (keys expire after 3 days)


@lru_cache(maxsize=1)
def _mart_reader() -> AnalyticsMartReader:
    settings = get_settings().trino
    return CachedMartReader(TrinoMartReader(trino_query(settings), settings.catalog))


def mart_reader() -> AnalyticsMartReader:
    return _mart_reader()


def admin(user: Annotated[Principal, Depends(principal)]) -> Principal:
    if user.role != "admin":
        raise HTTPException(403, "Organisation admin access required")
    return user


@lru_cache(maxsize=1)
def _live() -> RedisLiveOverlay:
    return RedisLiveOverlay(create_redis_client(get_settings().redis_url))


def live_overlay() -> LiveOverlayReader:
    return _live()


def today() -> date:
    return datetime.now(tz=UTC).date()


Reader = Annotated[AnalyticsMartReader, Depends(mart_reader)]
Live = Annotated[LiveOverlayReader, Depends(live_overlay)]
Today = Annotated[date, Depends(today)]
WithLive = Annotated[bool, Query(description="Add today's streaming overlay (Redis)")]
User = Annotated[Principal, Depends(principal)]
Admin = Annotated[Principal, Depends(admin)]
Instructor = Annotated[Principal, Depends(instructor)]
AsOf = Annotated[date | None, Query(description="Snapshot on or before this date (UTC)")]


def _course_scope(user: Principal, course_id: str | None) -> None:
    if course_id is None or course_id not in user.courses:
        raise HTTPException(403, "Course is outside your authorized scope")


@router.get("/lakehouse/session")
def session(user: User, reader: Reader) -> dict[str, Any]:
    courses = {c.id: c.name for c in reader.courses(user.courses)}
    orgs = {o.id: o.name for o in reader.organisations(user.organisations)}
    return {
        "id": user.id,
        "role": user.role,
        "courses": [{"id": c, "title": courses.get(c) or c} for c in user.courses],
        "organisations": [{"id": o, "name": orgs.get(o) or o} for o in user.organisations],
    }


# --- BR6 ----------------------------------------------------------------------------
@router.get("/admin/organisations/{organisation_id}/skill-progress")
def skill_progress(
    organisation_id: str, user: Admin, reader: Reader, as_of: AsOf = None
) -> dict[str, Any]:
    if organisation_id not in user.organisations:
        raise HTTPException(403, "Organisation is outside your authorized scope")
    snapshot = reader.org_progress(organisation_id, as_of)
    if snapshot is None:
        raise HTTPException(404, "No progress report has been built for this organisation yet")
    return asdict(snapshot)


# --- BR7 ----------------------------------------------------------------------------
def _videos(versions: list[VideoVersion]) -> list[dict[str, Any]]:
    """Group mart versions (newest first) into one entry per video."""
    out: dict[str, dict[str, Any]] = {}
    for v in versions:
        entry = out.setdefault(
            v.content_id,
            {"content_id": v.content_id, "title": v.title, "versions": []},
        )
        entry["versions"].append({"version": v.version, "duration_sec": v.duration_sec})
    return list(out.values())


@router.get("/instructor/courses/{course_id}/videos")
def course_videos(course_id: str, user: Instructor, reader: Reader) -> dict[str, Any]:
    _course_scope(user, course_id)
    return {"course_id": course_id, "videos": _videos(reader.course_videos(course_id))}


@router.get("/instructor/videos/{content_id}/interaction-heatmap")
def interaction_heatmap(
    content_id: str,
    user: Instructor,
    reader: Reader,
    overlay: Live,
    now: Today,
    version: Annotated[int | None, Query(ge=1, description="Newest version when omitted")] = None,
    live: WithLive = True,
) -> dict[str, Any]:
    versions = reader.video(content_id)
    if not versions:
        raise HTTPException(404, "No heatmap has been built for this video yet")
    _course_scope(user, versions[0].course_id)
    snapshot = reader.video_heatmap(content_id, version)
    if snapshot is None:
        raise HTTPException(404, f"No heatmap for version {version} of this video")
    body = asdict(snapshot)
    body["versions"] = _videos(versions)[0]["versions"]
    # live events carry no version: they belong to the newest one, so only it gets them
    newest = snapshot.video.version == versions[0].version
    body["live"] = _live_heatmap(overlay, snapshot, now) if live and newest else None
    return body


def _days_after(as_of: date, now: date) -> list[date]:
    start = max(as_of + timedelta(days=1), now - timedelta(days=LIVE_MAX_DAYS - 1))
    return [start + timedelta(days=i) for i in range((now - start).days + 1)]


def _live_heatmap(overlay: LiveOverlayReader, snapshot: Any, now: date) -> dict[str, Any] | None:
    days = _days_after(snapshot.as_of, now)
    if not days:
        return None
    try:
        live = overlay.heatmap(snapshot.video.content_id, days)
    except Exception as exc:  # the overlay is best effort; the mart still answers
        log.warning("live heatmap unavailable", error=str(exc))
        return None
    last = (snapshot.video.duration_sec or len(snapshot.seconds)) - 1
    merged: dict[int, list[int]] = {}
    for s in live.seconds:  # clamp past-the-end positions like the mart does
        acc = merged.setdefault(min(max(s.second, 0), last), [0, 0, 0, 0])
        acc[0] += s.play
        acc[1] += s.pause
        acc[2] += s.seek
        acc[3] = max(acc[3], s.learners)
    return {
        "days": [d.isoformat() for d in live.days],
        "updated_at": live.updated_at,
        "seconds": [
            {"second": k, "play": v[0], "pause": v[1], "seek": v[2], "learners": v[3]}
            for k, v in sorted(merged.items())
        ],
    }


# --- BR8 ----------------------------------------------------------------------------
@router.get("/instructor/courses/{course_id}/engagement-trend")
def engagement_trend(
    course_id: str,
    user: Instructor,
    reader: Reader,
    overlay: Live,
    now: Today,
    as_of: AsOf = None,
    live: WithLive = True,
) -> dict[str, Any]:
    _course_scope(user, course_id)
    snapshot = reader.engagement_trend(course_id, as_of)
    if snapshot is None:
        raise HTTPException(404, "No engagement trend has been built for this course yet")
    body = asdict(snapshot)
    body["declining_count"] = sum(1 for s in snapshot.learners if s.declining)
    body["live"] = None
    if live and as_of is None and snapshot.as_of < now:  # history views stay mart-only
        try:
            today_scores = overlay.engagement(course_id, now)
            scores = today_scores.scores
            body["live"] = {
                "day": now.isoformat(),
                "updated_at": today_scores.updated_at,
                "scores": scores,
                "course_avg": round(sum(scores.values()) / len(scores), 2) if scores else None,
            }
        except Exception as exc:
            log.warning("live engagement unavailable", error=str(exc))
    return body
