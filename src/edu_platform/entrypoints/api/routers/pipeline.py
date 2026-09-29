from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.serializers import learning_event_dict
from edu_platform.demo.simulator import Simulator
from edu_platform.entrypoints.api.deps import platform, simulator

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/stats")
async def stats(sim: Simulator = Depends(simulator)) -> dict[str, Any]:
    return sim.stats()


@router.get("/topics")
async def topics(p: DemoPlatform = Depends(platform)) -> list[dict[str, Any]]:
    return p.bus.topics()


@router.get("/topics/{topic}")
async def topic_messages(
    topic: str, limit: int = Query(20, ge=1, le=200), p: DemoPlatform = Depends(platform)
) -> list[dict[str, Any]]:
    return [
        {"key": m.key, "event_type": m.event_type, "at": m.at.isoformat(), "payload": m.payload}
        for m in p.bus.recent(topic, limit)
    ]


@router.get("/dlq")
async def dlq(
    limit: int = Query(20, ge=1, le=200), p: DemoPlatform = Depends(platform)
) -> list[dict[str, Any]]:
    return [
        {
            "event_id": d.raw.event_id,
            "reason": d.reason,
            "at": d.at.isoformat(),
            "payload": d.raw.payload,
        }
        for d in p.dlq.rows[-limit:][::-1]
    ]


@router.get("/silver")
async def silver(
    limit: int = Query(50, ge=1, le=500),
    learner_id: str | None = None,
    p: DemoPlatform = Depends(platform),
) -> list[dict[str, Any]]:
    rows = p.silver.all()
    if learner_id:
        pseudonym = p.pseudonym(learner_id)
        rows = [e for e in rows if e.learner_pseudonym == pseudonym]
    rows.sort(key=lambda e: e.received_at, reverse=True)
    return [learning_event_dict(e) for e in rows[:limit]]
