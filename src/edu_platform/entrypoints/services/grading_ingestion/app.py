"""Grading Ingestion Service (BR3) — HTTP entrypoint + Kafka queue.

POST /submissions accepts the code synchronously and returns 202 immediately;
the sandbox run happens in a separate worker via ``grading.submission_received.v1``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from edu_platform.contexts.grading.application.enqueue_submission import (
    EnqueueSubmission,
    EnqueueSubmissionCommand,
)
from edu_platform.contexts.grading.domain.model import Language
from edu_platform.contexts.grading.infrastructure.kafka_queue import (
    KafkaSubmissionQueue,
    NullPublisher,
)
from edu_platform.contexts.grading.infrastructure.redis_repository import (
    RedisCodeStore,
    RedisSubmissionRepository,
)
from edu_platform.demo import seed
from edu_platform.demo.serializers import submission_dict
from edu_platform.platform.config import Settings
from edu_platform.platform.messaging.kafka_producer import KafkaEventPublisher
from edu_platform.platform.storage.redis_client import create_redis_client
from edu_platform.shared_kernel.domain.ids import LearnerId, SubmissionId


class SubmissionBody(BaseModel):
    learner_id: str
    assignment_id: str
    code: str


def build_app(settings: Settings) -> FastAPI:
    client = create_redis_client(settings.redis_url)
    repo = RedisSubmissionRepository(client)
    code_store = RedisCodeStore(client)
    publisher = KafkaEventPublisher(
        settings.kafka.bootstrap_servers, client_id="edu-grading-ingest"
    )
    queue = KafkaSubmissionQueue(publisher)
    enqueue = EnqueueSubmission(repo, queue, code_store, NullPublisher())

    app = FastAPI(title="Grading Ingestion Service (BR3)")

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/submissions", status_code=202)
    def submit(body: SubmissionBody) -> dict[str, Any]:
        try:
            seed.learner(body.learner_id)
        except StopIteration:
            raise HTTPException(404, f"unknown learner {body.learner_id}") from None
        try:
            assignment = seed.assignment(body.assignment_id)
        except StopIteration:
            raise HTTPException(404, f"unknown assignment {body.assignment_id}") from None
        submission = enqueue.execute(
            EnqueueSubmissionCommand(
                learner_id=body.learner_id,
                assignment_id=body.assignment_id,
                language=Language(assignment.language),
                code=body.code,
                submitted_at=datetime.now(tz=UTC),
            )
        )
        return {"submission_id": submission.id, "status": "queued"}

    @app.get("/submissions/{submission_id}")
    def get_submission(submission_id: str) -> dict[str, Any]:
        submission = repo.get(SubmissionId(submission_id))
        if submission is None:
            raise HTTPException(404, f"unknown submission {submission_id}")
        return submission_dict(submission)

    @app.get("/learners/{learner_id}/submissions")
    def learner_submissions(learner_id: str) -> list[dict[str, Any]]:
        rows = repo.for_learner(LearnerId(learner_id))
        return [submission_dict(s, include_stdout=False) for s in rows]

    return app
