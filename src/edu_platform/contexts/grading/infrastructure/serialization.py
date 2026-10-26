"""JSON (de)serialisation of grading aggregates for Redis storage.

Submissions are value-ish dataclasses, so we serialise them field by field and
round-trip through explicit constructors rather than ``pickle`` or
``dataclasses.asdict`` (which would leak enum/type assumptions into storage).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from edu_platform.contexts.grading.domain.model import (
    ExecutionResult,
    Feedback,
    Language,
    Submission,
    SubmissionStatus,
    TestCaseResult,
    TestStatus,
)
from edu_platform.shared_kernel.domain.ids import AssignmentId, LearnerId, SubmissionId


def _result_to_dict(result: ExecutionResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "runtime_ms": result.runtime_ms,
        "memory_kb": result.memory_kb,
        "exit_code": result.exit_code,
        "tests": [
            {
                "test_case_id": t.test_case_id,
                "status": t.status.value,
                "expected": t.expected,
                "actual": t.actual,
                "diff": t.diff,
                "duration_ms": t.duration_ms,
            }
            for t in result.tests
        ],
    }


def _feedback_to_dict(feedback: Feedback | None) -> dict[str, Any] | None:
    if feedback is None:
        return None
    return {
        "summary": feedback.summary,
        "failed_tests": [
            {
                "test_case_id": t.test_case_id,
                "status": t.status.value,
                "expected": t.expected,
                "actual": t.actual,
                "diff": t.diff,
                "duration_ms": t.duration_ms,
            }
            for t in feedback.failed_tests
        ],
        "stderr_excerpt": feedback.stderr_excerpt,
        "hints": list(feedback.hints),
    }


def submission_to_dict(submission: Submission) -> dict[str, Any]:
    return {
        "id": submission.id,
        "learner_id": submission.learner_id,
        "assignment_id": submission.assignment_id,
        "language": submission.language.value,
        "code_ref": submission.code_ref,
        "submitted_at": submission.submitted_at.isoformat(),
        "status": submission.status.value,
        "attempt_number": submission.attempt_number,
        "result": _result_to_dict(submission.result),
        "feedback": _feedback_to_dict(submission.feedback),
    }


def _test_case_result(raw: dict[str, Any]) -> TestCaseResult:
    return TestCaseResult(
        test_case_id=raw["test_case_id"],
        status=TestStatus(raw["status"]),
        expected=raw.get("expected"),
        actual=raw.get("actual"),
        diff=raw.get("diff"),
        duration_ms=raw.get("duration_ms", 0),
    )


def submission_from_dict(raw: dict[str, Any]) -> Submission:
    result = None
    if raw.get("result") is not None:
        result = ExecutionResult(
            stdout=raw["result"]["stdout"],
            stderr=raw["result"]["stderr"],
            runtime_ms=raw["result"]["runtime_ms"],
            memory_kb=raw["result"]["memory_kb"],
            exit_code=raw["result"]["exit_code"],
            tests=tuple(_test_case_result(t) for t in raw["result"]["tests"]),
        )
    feedback = None
    if raw.get("feedback") is not None:
        feedback = Feedback(
            summary=raw["feedback"]["summary"],
            failed_tests=tuple(_test_case_result(t) for t in raw["feedback"]["failed_tests"]),
            stderr_excerpt=raw["feedback"].get("stderr_excerpt"),
            hints=tuple(raw["feedback"].get("hints", ())),
        )
    return Submission(
        id=SubmissionId(raw["id"]),
        learner_id=LearnerId(raw["learner_id"]),
        assignment_id=AssignmentId(raw["assignment_id"]),
        language=Language(raw["language"]),
        code_ref=raw["code_ref"],
        submitted_at=datetime.fromisoformat(raw["submitted_at"]),
        status=SubmissionStatus(raw["status"]),
        attempt_number=raw.get("attempt_number", 1),
        result=result,
        feedback=feedback,
    )
