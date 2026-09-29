from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from edu_platform.shared_kernel.domain import AggregateRoot, InvariantViolation, ValueObject
from edu_platform.shared_kernel.domain.ids import AssignmentId, LearnerId, SubmissionId

from .events import SubmissionGraded, SubmissionReceived


class Language(StrEnum):
    PYTHON = "python"
    SQL = "sql"
    JAVA = "java"
    JAVASCRIPT = "javascript"


class SubmissionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    GRADED = "graded"
    FAILED = "failed"  # sandbox infrastructure failure, not a wrong answer


class TestStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"  # runtime exception / compile error
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class TestCaseResult(ValueObject):
    test_case_id: str
    status: TestStatus
    expected: str | None = None
    actual: str | None = None
    diff: str | None = None  # unified diff, precomputed for feedback (BR3)
    duration_ms: int = 0


@dataclass(frozen=True)
class ExecutionResult(ValueObject):
    """Normalised sandbox output - the contract for feedback and for the BR4 mart."""

    stdout: str
    stderr: str
    runtime_ms: int
    memory_kb: int
    exit_code: int
    tests: tuple[TestCaseResult, ...]

    def __post_init__(self) -> None:
        if self.runtime_ms < 0 or self.memory_kb < 0:
            raise InvariantViolation("runtime and memory must be non-negative")

    @property
    def pass_rate(self) -> float:
        if not self.tests:
            return 0.0
        return sum(t.status is TestStatus.PASSED for t in self.tests) / len(self.tests)


@dataclass(frozen=True)
class Feedback(ValueObject):
    """Learner-facing explanation derived from ExecutionResult (BR3)."""

    summary: str
    failed_tests: tuple[TestCaseResult, ...]
    stderr_excerpt: str | None
    hints: tuple[str, ...] = ()


@dataclass(eq=False, kw_only=True)
class Submission(AggregateRoot[SubmissionId]):
    learner_id: LearnerId
    assignment_id: AssignmentId
    language: Language
    code_ref: str  # object storage key, never the code itself
    submitted_at: datetime
    status: SubmissionStatus = SubmissionStatus.QUEUED
    result: ExecutionResult | None = None
    feedback: Feedback | None = None
    attempt_number: int = field(default=1)

    @classmethod
    def receive(
        cls,
        submission_id: SubmissionId,
        learner_id: LearnerId,
        assignment_id: AssignmentId,
        language: Language,
        code_ref: str,
        submitted_at: datetime,
        attempt_number: int,
    ) -> Submission:
        sub = cls(
            id=submission_id,
            learner_id=learner_id,
            assignment_id=assignment_id,
            language=language,
            code_ref=code_ref,
            submitted_at=submitted_at,
            attempt_number=attempt_number,
        )
        sub.record(SubmissionReceived(aggregate_id=submission_id, learner_id=learner_id))
        return sub

    def grade(self, result: ExecutionResult, feedback: Feedback) -> None:
        if self.status is SubmissionStatus.GRADED:
            raise InvariantViolation("submission already graded")
        self.result = result
        self.feedback = feedback
        self.status = SubmissionStatus.GRADED
        self.record(
            SubmissionGraded(
                aggregate_id=self.id,
                learner_id=self.learner_id,
                assignment_id=self.assignment_id,
                pass_rate=result.pass_rate,
            )
        )
