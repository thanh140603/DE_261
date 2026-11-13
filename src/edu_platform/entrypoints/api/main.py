"""Demo API server: FastAPI app exposing every pipeline outcome (docs/api.md)
and serving the built web client from apps/web/dist.

Run with Docker Compose or uvicorn edu_platform.entrypoints.api.main:app --port 8000.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import psycopg
from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from edu_platform.br45.api import router as analytics_router
from edu_platform.br45.auth import StaffSessions
from edu_platform.br45.classroom import StudyError, load_enrollments
from edu_platform.br45.classroom_bots import run as run_bots
from edu_platform.br45.config import settings as analytics_settings
from edu_platform.br45.replay import Replay
from edu_platform.br45.replay_api import router as replay_router
from edu_platform.contexts.analytics.application.ports import MartUnavailable
from edu_platform.demo import handlers
from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.simulator import Simulator
from edu_platform.entrypoints.api.routers import (
    admin,
    advisor,
    classroom,
    content,
    events,
    instructor,
    lakehouse,
    learner,
    pipeline,
    reference,
    simulate,
    staff,
)
from edu_platform.platform.logging import configure_logging, get_logger
from edu_platform.shared_kernel.domain import DomainError, NotFoundError

ROOT = Path(__file__).resolve().parents[4]
RULES = ROOT / "infra" / "notification" / "rules.yaml"
WEB_DIST = ROOT / "apps" / "web" / "dist"
log = get_logger(__name__)


async def replay_clock(replay: Replay) -> None:
    while True:
        await asyncio.sleep(max(0, replay.deadline - replay.clock()))
        replay.tick()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("INFO", json=False)
    platform = DemoPlatform(RULES)
    handlers.register(platform)
    simulator = Simulator(platform)
    platform.broadcaster.bind_loop(asyncio.get_running_loop())
    if app.state.classroom_enabled:
        await asyncio.to_thread(load_enrollments, simulator)
        app.state.student_sessions = classroom.Sessions()
    await asyncio.to_thread(simulator.seed_history, grade=not app.state.classroom_enabled)
    app.state.platform = platform
    app.state.simulator = simulator
    task = None
    if app.state.br45_replay_enabled:
        replay = Replay()
        app.state.br45_replay = replay
        task = asyncio.create_task(replay_clock(replay))
    elif app.state.classroom_enabled:
        task = asyncio.create_task(run_bots(simulator))
    log.info("demo platform ready", silver=len(platform.silver.events))
    try:
        yield
    finally:
        simulator.stop()
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    app = FastAPI(title="DE_261 learning data platform (demo)", lifespan=lifespan)
    app.state.staff_sessions = StaffSessions()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    settings = analytics_settings()
    app.state.classroom_enabled = settings.classroom
    app.state.br45_replay_enabled = settings.replay and not settings.classroom
    app.include_router(
        replay_router if app.state.br45_replay_enabled else analytics_router, prefix="/api"
    )
    app.include_router(lakehouse.router, prefix="/api")
    app.include_router(content.router, prefix="/api")
    app.include_router(staff.router, prefix="/api")
    for router in (reference, pipeline, learner, instructor, advisor, admin, events):
        app.include_router(router.router, prefix="/api")
    if settings.classroom:
        app.include_router(classroom.router, prefix="/api")

        @app.middleware("http")
        async def classroom_headers(request: Request, call_next: Any) -> Response:
            response: Response = await call_next(request)
            response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response

        @app.exception_handler(psycopg.OperationalError)
        async def _classroom_unavailable(_: Request, exc: psycopg.OperationalError) -> JSONResponse:
            log.warning("Classroom database unavailable", error=type(exc).__name__)
            return JSONResponse(
                {"detail": "The classroom database is unavailable"}, status_code=503
            )

    else:
        app.include_router(simulate.router, prefix="/api")

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> Response:
        path = request.url.path
        if settings.classroom and path == "/api/classroom/student/session":
            return JSONResponse(
                {"detail": "Enter a classroom username and password"}, status_code=422
            )
        if path.startswith("/api/auth/staff/"):
            return JSONResponse(
                {"detail": "Invalid staff role or sign-in fields"}, status_code=422
            )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(StudyError)
    async def _study_error(_: Request, exc: StudyError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(content.ContentUnavailable)
    async def _content_unavailable(_: Request, exc: content.ContentUnavailable) -> JSONResponse:
        log.warning("content services unavailable", error=str(exc))
        return JSONResponse(
            {"detail": "Content services (PostgreSQL, MinIO, Redis, OpenSearch) are unavailable"},
            status_code=503,
        )

    @app.exception_handler(MartUnavailable)
    async def _mart_unavailable(_: Request, exc: MartUnavailable) -> JSONResponse:
        log.warning("lakehouse query failed", error=str(exc))
        return JSONResponse(
            {"detail": "The lakehouse warehouse (Trino) is unavailable; retry once it is running"},
            status_code=503,
        )

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
