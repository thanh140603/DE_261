import json
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from edu_platform.br45 import auth
from edu_platform.br45.config import settings
from edu_platform.entrypoints.api.deps import platform
from edu_platform.entrypoints.api.main import create_app
from edu_platform.entrypoints.api.routers import classroom
from edu_platform.entrypoints.api.routers.lakehouse import mart_reader

PASSWORD = "fixture-password-only"
ORIGIN = {"Origin": "https://testserver"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    digest = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1).hash(PASSWORD)
    accounts = [
        {
            "username": role,
            "id": f"{role}-id",
            "name": role.capitalize(),
            "role": role,
            "password_hash": digest,
            **scope,
        }
        for role, scope in (
            ("instructor", {"courses": ["c-sql-101"]}),
            ("advisor", {"courses": ["c-py-201"]}),
            ("admin", {"organisations": ["org-acme"]}),
        )
    ]
    monkeypatch.setenv("EDU_STAFF_ACCOUNTS", json.dumps(accounts))
    monkeypatch.setenv("EDU_BR45_MODE", "classroom")
    monkeypatch.setenv("EDU_BR45_AUTH", json.dumps({
        "script": {"id": "automation", "role": "advisor", "courses": ["c-py-201"]},
    }))
    settings.cache_clear()
    app = create_app()
    app.state.student_sessions = classroom.Sessions()
    monkeypatch.setattr(classroom, "authenticate", lambda *_: ("l-001", "Preset"))
    app.dependency_overrides[platform] = lambda: SimpleNamespace(risk_alerts=[
        {"course_id": "c-sql-101"}, {"course_id": "c-py-201"},
    ])
    app.dependency_overrides[mart_reader] = lambda: None
    yield TestClient(app, base_url="https://testserver")
    settings.cache_clear()


def session(role: str) -> str:
    return f"/api/auth/staff/{role}/session"


def login(client: TestClient, role: str, username: str | None = None):
    return client.post(
        session(role), json={"username": username or role, "password": PASSWORD}, headers=ORIGIN
    )


def test_independent_sessions_rotation_expiry_and_student_ownership(client, monkeypatch):
    now = 0.0
    monkeypatch.setattr(auth, "monotonic", lambda: now)
    assert client.get(session("instructor")).status_code == 401
    first = login(client, "instructor", "  InStRuCtOr ")
    assert first.status_code == 200
    assert first.json() == {
        "id": "instructor-id", "name": "Instructor", "role": "instructor",
        "courses": ["c-sql-101"], "organisations": [],
    }
    for attr in ("HttpOnly", "SameSite=strict", "Secure", "Max-Age=28800"):
        assert attr in first.headers["set-cookie"]
    assert first.headers["cache-control"] == "no-store"
    key = auth.cookie("instructor")
    old = client.cookies[key]
    assert login(client, "instructor").status_code == 200
    assert client.cookies[key] != old
    assert client.get(session("instructor"), headers={"Cookie": f"{key}={old}"}).status_code == 401
    assert login(client, "advisor").status_code == 200
    assert login(client, "admin").status_code == 200
    student = "/api/classroom/student/session"
    assert client.post(
        student, json={"username": "student", "password": PASSWORD}, headers=ORIGIN
    ).status_code == 200
    assert client.delete(session("instructor"), headers=ORIGIN).status_code == 204
    assert client.get(session("instructor")).status_code == 401
    assert client.get(session("advisor")).status_code == 200
    assert client.get(session("admin")).status_code == 200
    assert client.get(student).json()["id"] == "l-001"
    now = float(auth.SESSION_SECONDS)
    assert client.get(session("advisor")).status_code == 401


def test_role_scope_origin_and_bearer_priority(client):
    assert login(client, "advisor", "instructor").status_code == 403
    assert login(client, "advisor").status_code == 200
    assert login(client, "instructor").status_code == 200
    assert login(client, "admin").status_code == 200
    advisor = {"X-Staff-Role": "advisor"}
    instructor = {"X-Staff-Role": "instructor"}
    admin = {"X-Staff-Role": "admin"}
    alerts = "/api/advisor/demo-alerts"
    assert client.get(alerts).status_code == 401
    assert client.get(alerts, headers=instructor).status_code == 403
    assert client.get(alerts, headers=advisor).json() == [{"course_id": "c-py-201"}]
    assert client.get(alerts, headers={"Authorization": "Bearer script"}).status_code == 200
    assert client.get(
        alerts, headers=advisor | {"Authorization": "Basic invalid"}
    ).status_code == 401
    for path, headers in (
        ("/api/instructor/assessments?course_id=c-py-201", instructor),
        ("/api/admin/organisations/org-globex/progress", admin),
        ("/api/admin/organisations/org-globex/skill-progress", admin),
    ):
        assert client.get(path, headers=headers).status_code == 403
    for origin in ({}, {"Origin": "https://unrelated.example"}):
        assert client.post(
            "/api/instructor/content/v-sql-joins",
            headers=instructor | origin,
            json={"body": "sample"},
        ).status_code == 403
        assert client.delete(session("admin"), headers=origin).status_code == 403


def test_invalid_credentials_are_uniform_and_rate_limited(client):
    replies = [
        client.post(
            session("admin"), json={"username": username, "password": "wrong"}, headers=ORIGIN,
        )
        for username in ["admin", "missing"] * 5
    ]
    assert all(response.status_code == 401 for response in replies)
    error = {"detail": "Invalid username or password"}
    assert all(response.json() == error for response in replies)
    assert login(client, "admin").status_code == 429


def test_duplicate_normalized_usernames_are_rejected(monkeypatch):
    digest = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1).hash(PASSWORD)
    account = {
        "username": "advisor", "id": "one", "name": "Advisor", "role": "advisor",
        "password_hash": digest, "courses": ["c-py-201"],
    }
    monkeypatch.setenv(
        "EDU_STAFF_ACCOUNTS", json.dumps([account, account | {"username": " ADVISOR "}]),
    )
    with pytest.raises(ValueError, match="duplicate username"):
        auth.StaffSessions()
