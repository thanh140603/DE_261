from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from edu_platform.contexts.notification.domain.model import (
    Channel,
    DedupKey,
    Notification,
    NotificationContent,
    Priority,
)
from edu_platform.entrypoints.api.deps import (
    enrollment_repo,
    notification_repo,
)
from edu_platform.entrypoints.api.deps import (
    settings as settings_dep,
)
from edu_platform.entrypoints.api.main import create_app
from edu_platform.platform.config import Settings


class FakeNotifications:
    def for_recipient(self, recipient_id: str) -> list[Notification]:
        return [
            Notification(
                id="n1",
                recipient_id=recipient_id,
                dedup_key=DedupKey(recipient_id, "lms.deadline_approaching.v1", "c1"),
                channels=(Channel.IN_APP,),
                priority=Priority.HIGH,
                content=NotificationContent("Due soon", "Submit now", "/learner"),
                source_event_id="e1",
                source_event_type="lms.deadline_approaching.v1",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ]

    def count(self) -> int:
        return 1


class FakeGrading:
    def submit(self, learner_id: str, assignment_id: str, code: str) -> dict[str, object]:
        return {"submission_id": "s1", "status": "queued"}

    def submission(self, submission_id: str) -> dict[str, object]:
        return {
            "id": submission_id,
            "learner_id": "l-002",
            "assignment_id": "a-py-even",
            "language": "python",
            "status": "graded",
            "attempt_number": 1,
            "submitted_at": "2026-01-01T00:00:00+00:00",
            "result": None,
            "feedback": None,
        }

    def learner_submissions(self, learner_id: str) -> list[dict[str, object]]:
        return [self.submission("s1")]


def test_service_mode_reads_redis_model_and_proxies_grading() -> None:
    app = create_app()
    app.dependency_overrides[settings_dep] = lambda: Settings(br13_mode="service")
    app.dependency_overrides[notification_repo] = lambda: FakeNotifications()
    app.dependency_overrides[enrollment_repo] = lambda: None
    with TestClient(app) as client:
        app.state.grading = FakeGrading()

        notes = client.get("/api/learners/l-002/notifications")
        assert notes.status_code == 200
        assert notes.json()[0]["id"] == "n1"

        submitted = client.post(
            "/api/submissions",
            json={"learner_id": "l-002", "assignment_id": "a-py-even", "code": "print(1)"},
        )
        assert submitted.status_code == 202
        assert submitted.json() == {"submission_id": "s1", "status": "queued"}

        result = client.get("/api/submissions/s1")
        assert result.status_code == 200
        assert result.json()["status"] == "graded"

        rows = client.get("/api/learners/l-002/submissions")
        assert rows.status_code == 200
        assert rows.json()[0]["id"] == "s1"
