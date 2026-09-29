from __future__ import annotations

from typing import Any, Protocol

from edu_platform.contexts.grading.domain.model import ExecutionResult, Submission
from edu_platform.shared_kernel.domain.ids import LearnerId, SubmissionId


class SubmissionRepository(Protocol):
    def get(self, submission_id: SubmissionId) -> Submission | None: ...

    def save(self, submission: Submission) -> None: ...

    def for_learner(self, learner_id: LearnerId) -> list[Submission]: ...

    def all(self) -> list[Submission]: ...


class SubmissionQueue(Protocol):
    """Buffer between LMS and sandbox workers (Kafka topic grading.submission_received.v1)."""

    def enqueue(self, submission: Submission) -> None: ...


class CodeStore(Protocol):
    """Object storage for submitted code; the aggregate only keeps the reference."""

    def put(self, submission_id: SubmissionId, code: str) -> str: ...

    def get(self, code_ref: str) -> str: ...


class SandboxResultParser(Protocol):
    """Turns the heterogeneous raw worker log into the normalised ExecutionResult."""

    def parse(self, raw_log: dict[str, Any]) -> ExecutionResult: ...
