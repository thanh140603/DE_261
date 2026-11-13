"""BR3 projector: grading events -> LMS public submissions/grades.

Opt-in (``EDU_GRADING_PROJECT_TO_LMS=true`` and compose profile
``br13-project``). It exists so BR3 can own ``grading.*`` while the LMS/CDC
history still receives an explicit, auditable copy. Replays are idempotent
UPSERTs; a failed projection is retried by the consumer loop and then DLQ'd.
"""

from __future__ import annotations

from typing import Any

from edu_platform.contexts.grading.infrastructure.postgres_lms_projection import (
    PostgresLmsGradingProjection,
)
from edu_platform.platform.config import get_settings
from edu_platform.platform.logging import get_logger
from edu_platform.platform.messaging.kafka_consumer import KafkaConsumerLoop, KafkaMessage
from edu_platform.platform.messaging.kafka_producer import KafkaEventPublisher
from edu_platform.platform.messaging.topics import Topic

log = get_logger(__name__)


def _handler(projection: PostgresLmsGradingProjection) -> Any:
    def handle(message: KafkaMessage) -> None:
        if message.topic == Topic.SUBMISSION_RECEIVED.value:
            projection.record_queued(message.payload)
        elif message.topic == Topic.SUBMISSION_GRADED.value:
            projection.record_graded(message.payload)
        else:
            log.warning("projector ignored topic", topic=message.topic)

    return handle


def main() -> None:
    settings = get_settings()
    if not settings.grading_project_to_lms:
        log.info("grading projector disabled", reason="EDU_GRADING_PROJECT_TO_LMS is false")
        return
    projection = PostgresLmsGradingProjection(settings.postgres_dsn.get_secret_value())
    publisher = KafkaEventPublisher(
        settings.kafka.bootstrap_servers, client_id="edu-grading-projector"
    )
    loop = KafkaConsumerLoop(
        settings.kafka.bootstrap_servers,
        group_id="edu-grading-projector",
        topics=[Topic.SUBMISSION_RECEIVED.value, Topic.SUBMISSION_GRADED.value],
        dlq_publisher=lambda topic, payload: publisher.publish_raw(
            topic, key=None, payload=payload
        ),
        resilient=True,
    )
    loop.run(_handler(projection))


if __name__ == "__main__":
    main()
