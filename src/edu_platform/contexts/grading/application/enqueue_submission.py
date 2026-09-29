"""Use case: accept a submission from the LMS and buffer it for the sandbox (BR3).

The LMS gets a 202 immediately; sandbox load never blocks the learner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from edu_platform.contexts.grading.application.ports import (
    CodeStore,
    SubmissionQueue,
    SubmissionRepository,
)
from edu_platform.contexts.grading.domain.model import Language, Submission
from edu_platform.shared_kernel.application import EventPublisher
from edu_platform.shared_kernel.domain.ids import AssignmentId, LearnerId, SubmissionId, new_id


@dataclass(frozen=True)
class EnqueueSubmissionCommand:
    learner_id: str
    assignment_id: str
    language: Language
    code: str
    submitted_at: datetime


class EnqueueSubmission:
    def __init__(
        self,
        repo: SubmissionRepository,
        queue: SubmissionQueue,
        code_store: CodeStore,
        publisher: EventPublisher,
    ) -> None:
        self._repo = repo
        self._queue = queue
        self._code_store = code_store
        self._publisher = publisher

    def execute(self, command: EnqueueSubmissionCommand) -> Submission:
        submission_id = SubmissionId(new_id())
        learner_id = LearnerId(command.learner_id)
        attempt = 1 + sum(
            s.assignment_id == command.assignment_id for s in self._repo.for_learner(learner_id)
        )
        code_ref = self._code_store.put(submission_id, command.code)
        submission = Submission.receive(
            submission_id=submission_id,
            learner_id=learner_id,
            assignment_id=AssignmentId(command.assignment_id),
            language=command.language,
            code_ref=code_ref,
            submitted_at=command.submitted_at,
            attempt_number=attempt,
        )
        self._repo.save(submission)
        self._queue.enqueue(submission)
        self._publisher.publish(submission.pull_events())
        return submission
