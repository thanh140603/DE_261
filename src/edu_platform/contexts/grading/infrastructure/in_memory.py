"""In-memory grading adapters for tests and the demo server."""

from __future__ import annotations

from collections.abc import Callable

from edu_platform.contexts.grading.domain.model import Submission
from edu_platform.shared_kernel.domain.ids import LearnerId, SubmissionId


class InMemorySubmissionRepository:
    def __init__(self) -> None:
        self._rows: dict[str, Submission] = {}

    def get(self, submission_id: SubmissionId) -> Submission | None:
        return self._rows.get(submission_id)

    def save(self, submission: Submission) -> None:
        self._rows[submission.id] = submission

    def for_learner(self, learner_id: LearnerId) -> list[Submission]:
        return [s for s in self._rows.values() if s.learner_id == learner_id]

    def all(self) -> list[Submission]:
        return list(self._rows.values())


class InMemoryCodeStore:
    def __init__(self) -> None:
        self._blobs: dict[str, str] = {}

    def put(self, submission_id: SubmissionId, code: str) -> str:
        ref = f"mem://code/{submission_id}"
        self._blobs[ref] = code
        return ref

    def get(self, code_ref: str) -> str:
        return self._blobs[code_ref]


class CallbackSubmissionQueue:
    """Stands in for Kafka: hands the submission straight to a worker callback."""

    def __init__(self, on_enqueue: Callable[[Submission], None]) -> None:
        self._on_enqueue = on_enqueue
        self.enqueued: list[str] = []

    def enqueue(self, submission: Submission) -> None:
        self.enqueued.append(submission.id)
        self._on_enqueue(submission)
