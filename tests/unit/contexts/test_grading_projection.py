from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg

from edu_platform.contexts.grading.domain.model import (
    ExecutionResult,
    Feedback,
    Language,
    Submission,
    TestCaseResult,
    TestStatus,
)
from edu_platform.contexts.grading.infrastructure.postgres_grading_store import (
    PostgresGradingStore,
)
from edu_platform.contexts.grading.infrastructure.postgres_lms_projection import (
    PostgresLmsGradingProjection,
)
from edu_platform.shared_kernel.domain.ids import AssignmentId, LearnerId, SubmissionId


class FakeCursor:
    rowcount = 1


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> FakeCursor:
        self.calls.append((sql, params))
        return FakeCursor()

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _submission() -> Submission:
    sub = Submission.receive(
        submission_id=SubmissionId("s1"),
        learner_id=LearnerId("l-002"),
        assignment_id=AssignmentId("a-py-even"),
        language=Language.PYTHON,
        code_ref="edu:grading:code:s1",
        submitted_at=datetime(2026, 11, 11, tzinfo=UTC),
        attempt_number=1,
    )
    sub.grade(
        ExecutionResult(
            stdout="",
            stderr="",
            runtime_ms=10,
            memory_kb=100,
            exit_code=0,
            tests=(TestCaseResult("t1", TestStatus.PASSED, duration_ms=1),),
        ),
        Feedback("ok", (), None),
    )
    return sub


def test_grading_store_writes_only_grading_schema(monkeypatch) -> None:
    conn = FakeConnection()
    monkeypatch.setattr(psycopg, "connect", lambda _dsn: conn)
    store = PostgresGradingStore("unused")
    store.record_queued(_submission())
    store.record_graded(_submission())
    sql = "\n".join(call[0] for call in conn.calls)
    assert "grading.submissions" in sql
    assert "grading.grades" in sql
    assert "public." not in sql


def test_lms_projection_writes_public_schema(monkeypatch) -> None:
    conn = FakeConnection()
    monkeypatch.setattr(psycopg, "connect", lambda _dsn: conn)
    projection = PostgresLmsGradingProjection("unused")
    projection.record_queued(
        {
            "submission_id": "s1",
            "learner_id": "l-002",
            "assignment_id": "a-py-even",
            "attempt_number": 1,
            "language": "python",
            "code_ref": "edu:grading:code:s1",
            "submitted_at": "2026-11-11T00:00:00+00:00",
        }
    )
    projection.record_graded(
        {
            "aggregate_id": "s1",
            "learner_id": "l-002",
            "assignment_id": "a-py-even",
            "pass_rate": 1.0,
            "attempt_number": 1,
            "language": "python",
            "code_ref": "edu:grading:code:s1",
            "submitted_at": "2026-11-11T00:00:00+00:00",
        }
    )
    sql = "\n".join(call[0] for call in conn.calls)
    assert "public.submissions" in sql
    assert "public.grades" in sql
    assert "grading." not in sql


def test_projector_dispatches_both_topics() -> None:
    from edu_platform.entrypoints.services.grading_projector.main import _handler
    from edu_platform.platform.messaging.kafka_consumer import KafkaMessage
    from edu_platform.platform.messaging.topics import Topic

    class FakeProjection:
        queued: list[dict[str, Any]] = []
        graded: list[dict[str, Any]] = []

        def record_queued(self, payload: dict[str, Any]) -> None:
            self.queued.append(payload)

        def record_graded(self, payload: dict[str, Any]) -> None:
            self.graded.append(payload)

    projection = FakeProjection()
    handle = _handler(projection)  # type: ignore[arg-type]
    handle(
        KafkaMessage(
            topic=Topic.SUBMISSION_RECEIVED.value,
            key="s1",
            payload={"submission_id": "s1"},
            partition=0,
            offset=1,
        )
    )
    handle(
        KafkaMessage(
            topic=Topic.SUBMISSION_GRADED.value,
            key="s1",
            payload={"aggregate_id": "s1"},
            partition=0,
            offset=2,
        )
    )
    assert projection.queued == [{"submission_id": "s1"}]
    assert projection.graded == [{"aggregate_id": "s1"}]
