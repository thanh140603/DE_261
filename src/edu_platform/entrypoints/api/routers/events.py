"""Server-Sent Events endpoint feeding the live UI."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.simulator import Simulator
from edu_platform.entrypoints.api.deps import platform, simulator

router = APIRouter(tags=["events"])


@router.get("/events")
async def events(
    request: Request,
    p: DemoPlatform = Depends(platform),
    sim: Simulator = Depends(simulator),
) -> StreamingResponse:
    queue = p.broadcaster.subscribe()

    async def stream() -> AsyncIterator[str]:
        try:
            yield f"data: {json.dumps({'type': 'stats', 'at': None, 'payload': sim.stats()})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {data}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            p.broadcaster.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
