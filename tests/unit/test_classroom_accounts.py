import httpx
import pytest
from fastapi import FastAPI

from edu_platform.entrypoints.api.routers import classroom, learner


@pytest.mark.asyncio
async def test_classroom_sessions_enforce_ownership_and_revoke_on_logout(monkeypatch):
    app = FastAPI()
    app.state.classroom_enabled = True
    app.state.student_sessions = classroom.Sessions()

    async def platform_stub():
        return object()

    app.dependency_overrides[learner.platform] = platform_stub
    app.include_router(classroom.router, prefix="/api")
    app.include_router(learner.router, prefix="/api")

    async def immediate(function, *args):
        return function(*args)

    monkeypatch.setattr(classroom.asyncio, "to_thread", immediate)
    monkeypatch.setattr(
        classroom,
        "authenticate",
        lambda username, password: (
            ("l-001", "Preset") if (username, password) == ("an", "demo") else None
        ),
    )
    monkeypatch.setattr(
        learner.study,
        "feedback",
        lambda student, attempt=None: (
            [{"id": "owned"}] if (student, attempt) == ("l-001", "owned") else []
        ),
    )
    session = "/api/classroom/student/session"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/submissions/owned")).status_code == 401
        denied = await client.post(
            session,
            json={"username": "an", "password": "demo"},
            headers={"Origin": "http://another-origin"},
        )
        assert denied.status_code == 403
        rejected = await client.post(session, json={"username": "an", "password": "wrong"})
        assert rejected.status_code == 401
        logged_in = await client.post(session, json={"username": "an", "password": "demo"})
        assert logged_in.json()["name"] == "An Pham"
        assert "HttpOnly" in logged_in.headers["set-cookie"]
        assert "SameSite=strict" in logged_in.headers["set-cookie"]
        assert (await client.get("/api/submissions/owned")).json() == {"id": "owned"}
        assert (await client.get("/api/submissions/other")).status_code == 404
        assert (await client.get("/api/learners/l-003/submissions")).status_code == 403
        old_token = client.cookies[classroom.COOKIE]
        assert (await client.delete(session)).status_code == 204
        assert (
            await client.get(session, headers={"Cookie": f"{classroom.COOKIE}={old_token}"})
        ).status_code == 401
