"""End-to-end BR1/BR3 check against a running service-mode stack.

Run with ``EDU_BR13_BASE_URL=http://localhost:8000 pytest -m integration
tests/integration/test_br13_services.py`` after
``docker compose -f docker-compose.yml -f docker-compose.br13.yml up -d``.
"""

from __future__ import annotations

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE = os.getenv("EDU_BR13_BASE_URL")
if not BASE:
    pytest.skip("set EDU_BR13_BASE_URL to run the BR1/BR3 service test", allow_module_level=True)


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=10)


def _wait_for_graded(client: httpx.Client, submission_id: str) -> dict[str, object]:
    for _ in range(40):
        response = client.get(f"/api/submissions/{submission_id}")
        response.raise_for_status()
        body = response.json()
        if body["status"] in {"graded", "failed"}:
            return body
        time.sleep(0.25)
    raise AssertionError("submission did not finish grading")


def test_service_mode_end_to_end() -> None:
    with _client() as client:
        health = client.get("/api/health").json()
        assert health["mode"] == "service"

        client.post("/api/learners/l-002/enroll", json={"course_id": "c-ml-301"}).raise_for_status()
        submitted = client.post(
            "/api/submissions",
            json={
                "learner_id": "l-002",
                "assignment_id": "a-py-even",
                "code": "def sum_even(xs):\n    return sum(x for x in xs if x % 2 == 0)\n",
            },
        )
        assert submitted.status_code == 202
        submission_id = submitted.json()["submission_id"]
        graded = _wait_for_graded(client, submission_id)
        assert graded["status"] == "graded"
        assert graded["result"]["pass_rate"] == 0.8  # t5_pairs is intentionally broken

        rows = client.get("/api/learners/l-002/submissions").json()
        assert any(row["id"] == submission_id for row in rows)

        # BR1: the graded event must become an in-app notification through Kafka.
        for _ in range(30):
            notes = client.get("/api/learners/l-002/notifications").json()
            if any(n["source_event_type"] == "grading.submission_graded.v1" for n in notes):
                break
            time.sleep(0.25)
        else:
            raise AssertionError("graded submission did not create a notification")
