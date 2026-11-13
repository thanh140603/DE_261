import json
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI

from edu_platform.br45.config import settings
from edu_platform.br45.replay import COURSES, INTERVAL, Replay, assessment_rows
from edu_platform.br45.replay_api import router


def test_shared_replay_coalesces_timer_and_button_then_restarts_the_scenario():
    now = 0
    replay = Replay(lambda: now)

    def check(stage: int, points: int) -> None:
        assert replay.stage == stage
        for course in COURSES.values():
            questions, _ = assessment_rows(
                course,
                replay.stage,
                replay.anchor,
                replay.at,
                replay.at - timedelta(days=30),
                replay.at,
            )
            assert questions[0]["passed_evaluations"] == course.passes[stage]
            assert questions[0]["total_valid_evaluations"] == 24
            row = replay.history[course.learner(24)][0]
            assert (row["student_name"], row["score"]) == (course.outreach, points)

    check(0, 100)
    now = INTERVAL
    replay.tick()
    replay.tick(expected=0)
    check(1, 65)
    now += 10
    replay.tick(expected=1)
    assert replay.deadline == now + INTERVAL
    check(2, 50)
    assert {alert["status"] for alert in replay.alerts.values()} == {"RESOLVED"}
    replay.tick(expected=2)
    check(3, 0)
    replay.tick(expected=3)
    check(0, 100)
    assert {len(rows) for rows in replay.history.values()} == {1}


@pytest.mark.asyncio
async def test_dashboard_contracts_share_replay_and_keep_benchmarks_fixed(monkeypatch, request):
    monkeypatch.setenv(
        "EDU_BR45_AUTH",
        json.dumps(
            {
                f"{role}-demo": {"id": role, "role": role, "courses": list(COURSES)}
                for role in ("instructor", "advisor")
            }
        ),
    )
    settings.cache_clear()
    request.addfinalizer(settings.cache_clear)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.br45_replay = Replay(lambda: 0)
    instructor = {"Authorization": "Bearer instructor-demo"}
    advisor = {"Authorization": "Bearer advisor-demo"}
    grades = "/api/instructor/courses/c-py-201/questions/statistics"
    queue = "/api/advisor/courses/c-py-201/at-risk-students"
    alerts = "/api/advisor/alerts?course_id=c-py-201"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get(queue, headers=instructor)).status_code == 403
        assert (await client.get(queue)).status_code == 401
        session = (await client.get("/api/analytics/session", headers=advisor)).json()
        assert session["replay"] and len(session["courses"]) == 3
        question = (await client.get(grades, headers=instructor)).json()["items"][0]
        assert question["passed_evaluations"] == 2
        cases = f"/api/instructor/questions/{question['question_id']}/test-cases"
        assert (await client.get(cases, headers=instructor)).json()["items"][0][
            "state"
        ] == "SUSPICIOUS_TEST_CASE"
        row = (await client.get(queue + "?level=CRITICAL", headers=advisor)).json()["items"][0]
        assert row["student_name"] == "Linh Dao" and row["score"] == 100
        alert = (await client.get(alerts, headers=advisor)).json()["items"][0]
        action = f"/api/advisor/alerts/{alert['id']}/acknowledge"
        assert (await client.patch(action, headers=advisor)).json()["status"] == "ACKNOWLEDGED"
        benchmarks = "/api/analytics/replay/benchmarks"
        evidence = (await client.get(benchmarks, headers=instructor)).json()
        assert [row["records"] for row in evidence["br4"]] == [1000, 10000, 100000]
        assert all(row["runs"] == row["correct_runs"] == 3 for row in evidence["br5"])
        for revision, token in enumerate((instructor, advisor)):
            step = await client.post(
                "/api/analytics/replay/advance", headers=token, json={"revision": revision}
            )
            assert step.json()["revision"] == revision + 1
        result = (await client.get(alerts, headers=advisor)).json()["items"][0]
        assert result["id"] == alert["id"] and result["status"] == "RESOLVED"
        history = f"/api/advisor/students/{row['student_id']}/risk-history"
        observed = (await client.get(history, headers=advisor)).json()["items"]
        assert [item["score"] for item in observed] == [50, 65, 100]
        assert (await client.get(benchmarks, headers=advisor)).json() == evidence
