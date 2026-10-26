"""Grading normalizer (BR3) — consumes raw sandbox results, grades, persists.

Idempotent on ``(submission_id, worker_run_id)``: the result key is set only
after a successful grade, so a re-delivered or replayed result is a no-op.
"""

from __future__ import annotations

from typing import Any

from edu_platform.contexts.grading.application.normalize_execution_log import (
    NormalizeExecutionLog,
    NormalizeExecutionLogCommand,
)
from edu_platform.contexts.grading.domain.feedback_policy import FeedbackPolicy
from edu_platform.contexts.grading.infrastructure.redis_repository import RedisSubmissionRepository
from edu_platform.contexts.grading.infrastructure.sandbox_log_parser import SandboxLogParser
from edu_platform.platform.config import get_settings
from edu_platform.platform.messaging.kafka_consumer import KafkaConsumerLoop, KafkaMessage
from edu_platform.platform.messaging.kafka_producer import KafkaEventPublisher
from edu_platform.platform.messaging.topics import Topic
from edu_platform.platform.storage.redis_client import create_redis_client, key


def _handler(publisher: KafkaEventPublisher, repo: RedisSubmissionRepository, client: Any) -> Any:
    grade = NormalizeExecutionLog(repo, SandboxLogParser(), FeedbackPolicy(), publisher)

    def handle(message: KafkaMessage) -> None:
        payload = message.payload
        submission_id = str(payload["submission_id"])
        worker_run_id = str(payload["worker_run_id"])
        result_key = key("grading", "result", submission_id, worker_run_id)
        if client.exists(result_key):
            return
        grade.execute(NormalizeExecutionLogCommand(submission_id, worker_run_id, payload))
        client.set(result_key, "1", ex=7 * 24 * 3600)

    return handle


def main() -> None:
    settings = get_settings()
    client = create_redis_client(settings.redis_url)
    repo = RedisSubmissionRepository(client)
    publisher = KafkaEventPublisher(
        settings.kafka.bootstrap_servers, client_id="edu-grading-normalizer"
    )
    loop = KafkaConsumerLoop(
        settings.kafka.bootstrap_servers,
        group_id="edu-grading",
        topics=[Topic.SANDBOX_RESULT_RAW.value],
        dlq_publisher=lambda topic, payload: publisher.publish_raw(
            topic, key=None, payload=payload
        ),
    )
    loop.run(_handler(publisher, repo, client))


if __name__ == "__main__":
    main()
