"""Use case: consume raw sandbox output, normalise it, grade the submission (BR3).

Idempotent on (submission_id, worker_run_id): a replayed worker log is ignored.
SubmissionGraded is consumed by analytics (BR4 mart), notification (feedback
push) and risk (repeated-failure signal).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edu_platform.contexts.grading.application.ports import (
    SandboxResultParser,
    SubmissionRepository,
)
from edu_platform.contexts.grading.domain.feedback_policy import FeedbackPolicy
from edu_platform.contexts.grading.domain.model import Submission, SubmissionStatus
from edu_platform.shared_kernel.application import EventPublisher
from edu_platform.shared_kernel.domain import NotFoundError
from edu_platform.shared_kernel.domain.ids import SubmissionId


@dataclass(frozen=True)
class NormalizeExecutionLogCommand:
    submission_id: str
    worker_run_id: str
    raw_log: dict[str, Any]


class NormalizeExecutionLog:
    def __init__(
        self,
        repo: SubmissionRepository,
        parser: SandboxResultParser,
        feedback_policy: FeedbackPolicy,
        publisher: EventPublisher,
    ) -> None:
        self._repo = repo
        self._parser = parser
        self._feedback_policy = feedback_policy
        self._publisher = publisher
        self._seen_runs: set[tuple[str, str]] = set()

    def execute(self, command: NormalizeExecutionLogCommand) -> Submission:
        key = (command.submission_id, command.worker_run_id)
        submission = self._repo.get(SubmissionId(command.submission_id))
        if submission is None:
            raise NotFoundError(f"submission {command.submission_id} not found")
        if key in self._seen_runs or submission.status is SubmissionStatus.GRADED:
            return submission
        self._seen_runs.add(key)
        result = self._parser.parse(command.raw_log)
        feedback = self._feedback_policy.build(result, submission.language)
        submission.grade(result, feedback)
        self._repo.save(submission)
        self._publisher.publish(submission.pull_events())
        return submission
