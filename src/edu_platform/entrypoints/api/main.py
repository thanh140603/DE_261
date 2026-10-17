"""Demo API server: FastAPI app exposing every pipeline outcome (docs/api.md)
and serving the built web client from apps/web/dist.

Run with Docker Compose or uvicorn edu_platform.entrypoints.api.main:app --port 8000.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from edu_platform.br45.api import router as analytics_router
from edu_platform.demo import handlers
from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.simulator import Simulator
from edu_platform.entrypoints.api.routers import (
    admin,
    advisor,
    events,
    instructor,
    learner,
    pipeline,
    reference,
    simulate,
)
from edu_platform.platform.logging import configure_logging, get_logger
from edu_platform.shared_kernel.domain import DomainError, NotFoundError

ROOT = Path(__file__).resolve().parents[4]
RULES = ROOT / "infra" / "notification" / "rules.yaml"
WEB_DIST = ROOT / "apps" / "web" / "dist"
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("INFO", json=False)
    platform = DemoPlatform(RULES)
    handlers.register(platform)
    simulator = Simulator(platform)
    platform.broadcaster.bind_loop(asyncio.get_running_loop())
    await asyncio.to_thread(simulator.seed_history)
    app.state.platform = platform
    app.state.simulator = simulator
    log.info("demo platform ready", silver=len(platform.silver.events))
    yield
    simulator.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="DE_261 learning data platform (demo)", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(analytics_router, prefix="/api")
    for router in (reference, simulate, pipeline, learner, instructor, advisor, admin, events):
        app.include_router(router.router, prefix="/api")

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            candidate = WEB_DIST / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

    return app


app = create_app()
