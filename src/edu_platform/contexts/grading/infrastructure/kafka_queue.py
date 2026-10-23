"""Kafka-backed submission queue (BR3).

The ``SubmissionQueue`` port publishes the full queue payload to
``grading.submission_received.v1``. The domain ``SubmissionReceived`` event is
deliberately *not* published by ``EnqueueSubmission`` here (its publisher is a
no-op), so the queue topic has exactly one producer and one message shape.
"""

from __future__ import annotations

from typing import Any

from edu_platform.contexts.grading.domain.model import Submission
from edu_platform.platform.messaging.topics import Topic


class KafkaSubmissionQueue:
    def __init__(self, publisher: Any) -> None:
        self._publisher = publisher

    def enqueue(self, submission: Submission) -> None:
        self._publisher.publish_raw(
            Topic.SUBMISSION_RECEIVED.value,
            key=submission.id,
            payload={
                "submission_id": submission.id,
                "learner_id": submission.learner_id,
                "assignment_id": submission.assignment_id,
                "language": submission.language.value,
                "code_ref": submission.code_ref,
                "attempt_number": submission.attempt_number,
                "submitted_at": submission.submitted_at.isoformat(),
            },
        )


class NullPublisher:
    """EventPublisher that discards events (used where the queue already emits)."""

    def publish(self, events: list[Any], *, topic: str | None = None) -> None:
        return None
