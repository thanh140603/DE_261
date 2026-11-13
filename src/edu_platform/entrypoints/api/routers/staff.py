"""Browser session endpoints for pre-provisioned staff accounts."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from edu_platform.br45.auth import (
    SESSION_SECONDS,
    StaffIdentity,
    StaffRole,
    StaffSessions,
    cookie,
    log,
    same_origin,
)

router = APIRouter(prefix="/auth/staff", tags=["Staff authentication"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def use_sessions(request: Request) -> StaffSessions:
    sessions: StaffSessions = request.app.state.staff_sessions
    return sessions


@router.post("/{role}/session", response_model=StaffIdentity)
async def login(
    role: StaffRole, body: Credentials, request: Request, response: Response
) -> StaffIdentity:
    sessions = use_sessions(request)
    same_origin(request, sessions)
    sessions.limit(request.client.host if request.client else "local")
    async with sessions.verifications:
        account = await asyncio.to_thread(sessions.authenticate, body.username, body.password)
    if account is None:
        log.warning("Staff sign-in rejected")
        raise HTTPException(401, "Invalid username or password")
    if account.role != role:
        raise HTTPException(403, "This account cannot sign in to this workspace")
    name = cookie(role)
    token = sessions.issue(account, request.cookies.get(name, ""))
    response.set_cookie(
        name, token, max_age=SESSION_SECONDS, httponly=True, samesite="strict",
        path="/api",
        secure=request.url.scheme == "https" or sessions.origin.startswith("https://"),
    )
    response.headers["Cache-Control"] = "no-store"
    return StaffIdentity.model_validate(account, from_attributes=True)


@router.get("/{role}/session", response_model=StaffIdentity)
async def current(role: StaffRole, request: Request, response: Response) -> StaffIdentity:
    account = use_sessions(request).find(role, request.cookies.get(cookie(role), ""))
    if account is None:
        raise HTTPException(401, "Sign in to continue", headers={"Cache-Control": "no-store"})
    response.headers["Cache-Control"] = "no-store"
    return StaffIdentity.model_validate(account, from_attributes=True)


@router.delete("/{role}/session", status_code=204)
async def logout(role: StaffRole, request: Request, response: Response) -> None:
    sessions = use_sessions(request)
    same_origin(request, sessions)
    name = cookie(role)
    sessions.revoke(role, request.cookies.get(name, ""))
    response.delete_cookie(
        name, httponly=True, samesite="strict",
        path="/api",
        secure=request.url.scheme == "https" or sessions.origin.startswith("https://"),
    )
    response.headers["Cache-Control"] = "no-store"
