"""Grading sandbox worker (BR3) — consumes the submission queue and runs code.

Each queue message is claimed with ``SET NX`` so a re-delivered message does not
launch a second sandbox run; on failure the claim is released so the loop can
retry or forward to the DLQ.
"""

from __future__ import annotations

from typing import Any

from edu_platform.demo import seed
from edu_platform.demo.sandbox import DemoSandboxWorker
from edu_platform.platform.config import get_settings
from edu_platform.platform.messaging.kafka_consumer import KafkaConsumerLoop, KafkaMessage
from edu_platform.platform.messaging.kafka_producer import KafkaEventPublisher
from edu_platform.platform.messaging.topics import Topic
from edu_platform.platform.storage.redis_client import create_redis_client, key


def _handler(publisher: KafkaEventPublisher, client: Any, code_store: Any) -> Any:
    def handle(message: KafkaMessage) -> None:
        payload = message.payload
        submission_id = str(payload["submission_id"])
        claim = key("grading", "worker", submission_id)
        if not client.set(claim, "1", nx=True, ex=300):
            return  # another worker is running this submission
        try:
            code = code_store.get(payload["code_ref"])
            assignment = seed.assignment(payload["assignment_id"])
            log = DemoSandboxWorker().run(submission_id, assignment, code)
            publisher.publish_raw(Topic.SANDBOX_RESULT_RAW.value, key=submission_id, payload=log)
        except Exception:
            client.delete(claim)
            raise

    return handle


def main() -> None:
    settings = get_settings()
    client = create_redis_client(settings.redis_url)
    from edu_platform.contexts.grading.infrastructure.redis_repository import RedisCodeStore

    code_store = RedisCodeStore(client)
    publisher = KafkaEventPublisher(
        settings.kafka.bootstrap_servers, client_id="edu-grading-worker"
    )
    loop = KafkaConsumerLoop(
        settings.kafka.bootstrap_servers,
        group_id="edu-grading-worker",
        topics=[Topic.SUBMISSION_RECEIVED.value],
        dlq_publisher=lambda topic, payload: publisher.publish_raw(
            topic, key=None, payload=payload
        ),
    )
    loop.run(_handler(publisher, client, code_store))


if __name__ == "__main__":
    main()
