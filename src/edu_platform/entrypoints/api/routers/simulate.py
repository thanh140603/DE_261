from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from edu_platform.demo import seed
from edu_platform.demo.simulator import Simulator
from edu_platform.entrypoints.api.deps import simulator

router = APIRouter(prefix="/simulate", tags=["simulate"])


class StartBody(BaseModel):
    rate_per_sec: float | None = None


class TelemetryBody(BaseModel):
    learner_id: str
    verb: str
    course_id: str | None = None
    content_id: str | None = None
    video_position_sec: int | None = None
    platform: str | None = None
    late_seconds: int = 0
    schema_version: Literal["1.0", "1.1"] = "1.1"
    malformed: bool = False


class BurstBody(BaseModel):
    count: int = Field(100, ge=1, le=5000)


class LmsEventBody(BaseModel):
    event_type: Literal["assignment_created", "deadline_approaching", "course_updated"]
    course_id: str
    assignment_id: str | None = None
    hours_to_deadline: float | None = None
    title: str | None = None


class CdcBody(BaseModel):
    table: Literal["lesson_progress", "enrollments", "grades", "submissions"]
    learner_id: str
    course_id: str
    lesson_id: str | None = None
    percent_done: int | None = None
    status: str | None = None
    score: float | None = None
    assignment_id: str | None = None


@router.post("/start")
async def start(body: StartBody, sim: Simulator = Depends(simulator)) -> dict[str, Any]:
    sim.start(body.rate_per_sec)
    return {"running": True, "rate_per_sec": sim.rate_per_sec}


@router.post("/stop")
async def stop(sim: Simulator = Depends(simulator)) -> dict[str, Any]:
    sim.stop()
    return {"running": False}


@router.get("/status")
async def status(sim: Simulator = Depends(simulator)) -> dict[str, Any]:
    return {"running": sim.running, "rate_per_sec": sim.rate_per_sec, "generated": sim.generated}


@router.post("/telemetry")
async def telemetry(body: TelemetryBody, sim: Simulator = Depends(simulator)) -> dict[str, Any]:
    try:
        learner = seed.learner(body.learner_id)
    except StopIteration as exc:
        raise HTTPException(404, f"unknown learner {body.learner_id}") from exc
    occurred_at = datetime.now(tz=UTC) - timedelta(seconds=max(0, body.late_seconds))
    payload = sim.make_payload(
        learner,
        verb=body.verb,
        occurred_at=occurred_at,
        course_id=body.course_id,
        content_id=body.content_id,
        video_position_sec=body.video_position_sec,
        platform=body.platform,
        schema_version=body.schema_version,
    )
    if body.malformed:
        payload.pop("course_id", None)
        payload["occurred_at"] = "not-a-timestamp"
    event_id = sim.ingest(payload)
    outcome, reason = sim.outcome(event_id)
    return {"event_id": event_id, "outcome": outcome, "reason": reason}


@router.post("/burst")
async def burst(body: BurstBody, sim: Simulator = Depends(simulator)) -> dict[str, Any]:
    result = sim.generate(body.count)
    sim.p.broadcaster.publish("stats", sim.stats())
    return result


@router.post("/lms-event")
async def lms_event(body: LmsEventBody, sim: Simulator = Depends(simulator)) -> dict[str, Any]:
    course = seed.course(body.course_id)
    fields: dict[str, Any] = {"assignment_id": body.assignment_id}
    if body.assignment_id:
        fields["title"] = body.title or seed.assignment(body.assignment_id).title
    else:
        fields["title"] = body.title or f"{course.title}: new material"
    if body.event_type == "deadline_approaching":
        fields["hours_to_deadline"] = (
            body.hours_to_deadline if body.hours_to_deadline is not None else 12
        )
        fields["due_at"] = (
            datetime.now(tz=UTC) + timedelta(hours=fields["hours_to_deadline"])
        ).isoformat()
    if body.event_type == "course_updated":
        fields["change_summary"] = body.title or "Course content was updated."
    result = sim.emit_lms_event(body.event_type, body.course_id, **fields)
    sim.p.broadcaster.publish("stats", sim.stats())
    return {
        "event_id": result["event_id"],
        "notifications": {"created": result["created"], "suppressed": result["suppressed"]},
    }


@router.post("/cdc")
async def cdc(body: CdcBody, sim: Simulator = Depends(simulator)) -> dict[str, Any]:
    fields = body.model_dump(exclude={"table", "learner_id", "course_id"})
    risk = sim.emit_cdc(body.table, body.learner_id, body.course_id, **fields)
    sim.p.broadcaster.publish("stats", sim.stats())
    return {"applied": True, "risk": risk}


@router.post("/scenario/{name}")
async def scenario(name: str, sim: Simulator = Depends(simulator)) -> dict[str, Any]:
    try:
        result = sim.scenario(name)
    except KeyError as exc:
        raise HTTPException(404, f"unknown scenario {name}") from exc
    sim.p.broadcaster.publish("stats", sim.stats())
    return result
