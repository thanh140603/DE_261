from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from edu_platform.contexts.analytics.domain.model import TimeWindow
from edu_platform.contexts.content.application.publish_content_version import (
    PublishContentVersionCommand,
)
from edu_platform.demo import seed
from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.simulator import Simulator
from edu_platform.entrypoints.api.deps import platform, simulator
from edu_platform.shared_kernel.domain.ids import ContentId

router = APIRouter(prefix="/instructor", tags=["instructor"])


@router.get("/assessments")
async def assessments(
    course_id: str | None = None, p: DemoPlatform = Depends(platform)
) -> list[dict[str, Any]]:
    now = datetime.now(tz=UTC)
    window = TimeWindow(now - timedelta(days=30), now + timedelta(minutes=1))
    rows = p.assessment_mart.execute(p.submissions.all(), window)
    out = []
    for r in rows:
        assignment = seed.assignment(r.assignment_id)
        if course_id and assignment.course_id != course_id:
            continue
        out.append(
            {
                "assignment_id": r.assignment_id,
                "assignment_title": assignment.title,
                "item_id": r.item_id,
                "attempts": r.attempts,
                "passes": r.passes,
                "pass_rate": r.pass_rate,
                "assignment_median_pass_rate": r.assignment_median_pass_rate,
                "is_anomalous": r.is_anomalous,
            }
        )
    return out


@router.get("/videos/{content_id}/heatmap")
async def heatmap(content_id: str, p: DemoPlatform = Depends(platform)) -> dict[str, Any]:
    found = seed.lesson_by_content(content_id)
    if found is None:
        raise HTTPException(404, f"unknown content {content_id}")
    _, lesson = found
    buckets = p.video_heatmap.execute(p.silver.all(), ContentId(content_id), lesson.duration_sec)
    return {
        "content_id": content_id,
        "title": lesson.title,
        "duration_sec": lesson.duration_sec,
        "buckets": [
            {
                "second": b.second,
                "play": b.play_count,
                "pause": b.pause_count,
                "seek": b.seek_count,
                "learners": b.unique_learners,
            }
            for b in buckets
        ],
    }


@router.get("/courses/{course_id}/engagement")
async def engagement(course_id: str, p: DemoPlatform = Depends(platform)) -> dict[str, Any]:
    try:
        seed.course(course_id)
    except StopIteration as exc:
        raise HTTPException(404, f"unknown course {course_id}") from exc
    trend = p.engagement.execute(
        p.silver.all(), course_id, datetime.now(tz=UTC) + timedelta(minutes=1), timedelta(days=7), 4
    )
    return {
        "windows": [
            {"start": w.start.isoformat(), "end": w.end.isoformat()} for w in trend.windows
        ],
        "learners": [
            {"pseudonym": s.learner_pseudonym, "scores": s.scores, "declining": s.declining}
            for s in trend.series
        ],
        "course_avg": trend.course_avg,
    }


def _content_record(p: DemoPlatform, content_id: str) -> dict[str, Any]:
    item = p.content.get(ContentId(content_id))
    if item is None:
        raise HTTPException(404, f"unknown content {content_id}")
    return {
        "id": item.id,
        "course_id": item.course_id,
        "title": item.title,
        "content_type": item.content_type.value,
        "versions": [
            {
                "number": v.number,
                "published_at": v.published_at.isoformat(),
                "checksum": v.checksum_sha256[:12],
            }
            for v in item.versions
        ],
        "indexed_version": item.indexed_version,
        "chunk_count": p.vectors.count(ContentId(content_id)),
        "cache_state": p.cache.state(ContentId(content_id)),
        "search_version": p.search.indexed_version(ContentId(content_id)),
    }


@router.get("/content/{content_id}")
async def content(content_id: str, p: DemoPlatform = Depends(platform)) -> dict[str, Any]:
    return _content_record(p, content_id)


class ContentBody(BaseModel):
    title: str | None = None
    body: str


@router.post("/content/{content_id}")
async def publish(
    content_id: str, body: ContentBody, sim: Simulator = Depends(simulator)
) -> dict[str, Any]:
    p = sim.p
    item = p.content.get(ContentId(content_id))
    if item is None:
        raise HTTPException(404, f"unknown content {content_id}")
    result = p.publish_content.execute(
        PublishContentVersionCommand(content_id, body.body, body.title, datetime.now(tz=UTC))
    )
    created = 0
    if any(s.status == "done" for s in result.steps):
        out = sim.emit_lms_event(
            "course_updated",
            item.course_id,
            content_id=content_id,
            change_summary=f"{item.title} was updated to version {result.version}.",
        )
        created = out["created"]
    p.broadcaster.publish(
        "content.sync",
        {"content_id": content_id, "version": result.version, "steps": len(result.steps)},
    )
    p.broadcaster.publish("stats", sim.stats())
    return {
        "version": result.version,
        "sync": [{"step": s.step, "status": s.status, "ms": s.ms} for s in result.steps],
        "notifications_created": created,
        "content": _content_record(p, content_id),
    }
