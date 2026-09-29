from __future__ import annotations

from datetime import UTC, datetime

import pytest

from edu_platform.contexts.grading.domain.events import SubmissionGraded, SubmissionReceived
from edu_platform.contexts.grading.domain.model import (
    ExecutionResult,
    Feedback,
    Language,
    Submission,
    SubmissionStatus,
    TestCaseResult,
    TestStatus,
)
from edu_platform.shared_kernel.domain import InvariantViolation
from edu_platform.shared_kernel.domain.ids import AssignmentId, LearnerId, SubmissionId


def _result(passed: int, failed: int) -> ExecutionResult:
    tests = [TestCaseResult(f"t{i}", TestStatus.PASSED) for i in range(passed)] + [
        TestCaseResult(f"f{i}", TestStatus.FAILED) for i in range(failed)
    ]
    return ExecutionResult("", "", 10, 1024, 0, tuple(tests))


def _submission() -> Submission:
    return Submission.receive(
        SubmissionId("s1"),
        LearnerId("l1"),
        AssignmentId("a1"),
        Language.PYTHON,
        "s3://code/s1.py",
        datetime(2026, 9, 29, tzinfo=UTC),
        1,
    )


def test_pass_rate() -> None:
    assert _result(3, 1).pass_rate == pytest.approx(0.75)
    assert _result(0, 0).pass_rate == 0.0


def test_receive_records_event() -> None:
    sub = _submission()
    assert sub.status is SubmissionStatus.QUEUED
    assert isinstance(sub.pull_events()[0], SubmissionReceived)


def test_grade_transitions_and_emits() -> None:
    sub = _submission()
    sub.pull_events()
    sub.grade(_result(2, 2), Feedback("2/4 passed", (), None))
    assert sub.status is SubmissionStatus.GRADED
    (event,) = sub.pull_events()
    assert isinstance(event, SubmissionGraded)
    assert event.pass_rate == pytest.approx(0.5)


def test_cannot_grade_twice() -> None:
    sub = _submission()
    sub.grade(_result(1, 0), Feedback("ok", (), None))
    with pytest.raises(InvariantViolation):
        sub.grade(_result(1, 0), Feedback("ok", (), None))
