"""Local classroom sign-in and lesson actions."""

from __future__ import annotations

import asyncio
from collections import deque
from hmac import compare_digest
from secrets import token_urlsafe
from time import monotonic
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from edu_platform.br45.api import User
from edu_platform.br45.classroom import lesson_activity, lesson_progress, password_hash
from edu_platform.br45.db import connect
from edu_platform.br45.replay_api import benchmark_results
from edu_platform.demo import seed
from edu_platform.platform.logging import get_logger

router = APIRouter(tags=["BR45 classroom"])
COOKIE = "de261_student_session"
SESSION_SECONDS = 8 * 60 * 60
log = get_logger(__name__)


class Sessions:
    def __init__(self) -> None:
        self.active: dict[str, tuple[str, str, float]] = {}
        self.attempts: dict[str, deque[float]] = {}
        self.verifications = asyncio.Semaphore(2)

    def limit(self, peer: str) -> None:
        now = monotonic()
        attempts = self.attempts.setdefault(peer, deque())
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, "Too many sign-in attempts. Try again in a minute.")
        attempts.append(now)

    def find(self, token: str) -> tuple[str, str, float] | None:
        current = self.active.get(token)
        if current and current[2] <= monotonic():
            self.active.pop(token, None)
            return None
        return current


def enabled(request: Request) -> bool:
    return bool(getattr(request.app.state, "classroom_enabled", False))


def same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Use the classroom app to perform this action")


def session_state(request: Request) -> tuple[str, str, float]:
    sessions: Sessions = request.app.state.student_sessions
    current = sessions.find(request.cookies.get(COOKIE, ""))
    if current is None:
        raise HTTPException(401, "Sign in with a classroom student account")
    return current


def owner(request: Request, expected: str | None = None) -> str:
    if request.method not in {"GET", "HEAD"}:
        same_origin(request)
    student = session_state(request)[0]
    if expected is not None and student != expected:
        log.warning("Classroom learner ownership check rejected")
        raise HTTPException(403, "This learner record belongs to another student")
    return student


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def authenticate(username: str, password: str) -> tuple[str, str] | None:
    with connect() as conn:
        account = conn.execute(
            "SELECT student_id,profile,salt,password_hash "
            "FROM classroom.accounts WHERE username=%s",
            (username,),
        ).fetchone()
    salt = account["salt"] if account else bytes(16)
    supplied = password_hash(password, salt)
    if account and compare_digest(supplied, account["password_hash"]):
        return account["student_id"], account["profile"]
    return None


def profile(student: str, preset: str) -> dict[str, str]:
    return {"id": student, "name": seed.learner(student).name, "profile": preset}


@router.post("/classroom/student/session")
async def login(body: Credentials, request: Request, response: Response) -> dict[str, str]:
    same_origin(request)
    sessions: Sessions = request.app.state.student_sessions
    sessions.limit(request.client.host if request.client else "local")
    async with sessions.verifications:
        account = await asyncio.to_thread(
            authenticate, body.username.strip().lower(), body.password
        )
    if account is None:
        log.warning("Classroom student sign-in rejected")
        raise HTTPException(401, "Invalid classroom username or password")
    now = monotonic()
    current = request.cookies.get(COOKIE, "")
    sessions.active = {
        token: value
        for token, value in sessions.active.items()
        if value[2] > now and token != current
    }
    token = token_urlsafe(32)
    sessions.active[token] = (*account, now + SESSION_SECONDS)
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )
    response.headers["Cache-Control"] = "no-store"
    return profile(*account)


@router.get("/classroom/student/session")
async def current(request: Request, response: Response) -> dict[str, str]:
    student, preset, _ = session_state(request)
    response.headers["Cache-Control"] = "no-store"
    return profile(student, preset)


@router.delete("/classroom/student/session", status_code=204)
async def logout(request: Request, response: Response) -> None:
    same_origin(request)
    sessions: Sessions = request.app.state.student_sessions
    sessions.active.pop(request.cookies.get(COOKIE, ""), None)
    response.delete_cookie(COOKIE)


class LessonAction(BaseModel):
    kind: Literal["lesson_view", "lesson_complete"]
    request_id: UUID


@router.get("/classroom/student/lessons")
async def lessons(request: Request) -> list[dict[str, Any]]:
    return await asyncio.to_thread(lesson_progress, owner(request))


@router.post("/classroom/student/lessons/{lesson_id}/activity", status_code=204)
async def study(lesson_id: str, body: LessonAction, request: Request) -> None:
    await asyncio.to_thread(
        lesson_activity,
        owner(request),
        lesson_id,
        body.kind,
        str(body.request_id),
    )


@router.get("/analytics/replay/benchmarks")
async def benchmarks(user: User) -> dict[str, Any]:
    if user.role not in {"instructor", "advisor"}:
        raise HTTPException(403, "Staff access required")
    try:
        return benchmark_results()
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Measured benchmark evidence is unavailable") from exc
