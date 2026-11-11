"""Kafka -> SSE bridge for service mode (BR1/BR3).

In ``demo`` mode every write already happens in-process, so ``Broadcaster`` sees
it directly. In ``service`` mode the notification and grading services run in
other containers: the API must consume their outcome topics and forward them to
the browser, otherwise the UI only refreshes on navigation.
"""

from __future__ import annotations

import threading
from typing import Any

from edu_platform.demo.sse import Broadcaster
from edu_platform.platform.config import Settings
from edu_platform.platform.logging import get_logger
from edu_platform.platform.messaging.topics import Topic
from edu_platform.platform.serialization.codec import JsonCodec

log = get_logger(__name__)

_TOPICS = [Topic.NOTIFICATION_DISPATCHED.value, Topic.SUBMISSION_GRADED.value]


class KafkaSseBridge:
    def __init__(self, settings: Settings, broadcaster: Broadcaster) -> None:
        self._settings = settings
        self._broadcaster = broadcaster
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._codec = JsonCodec()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="kafka-sse", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        from confluent_kafka import Consumer

        consumer = Consumer(
            {
                "bootstrap.servers": self._settings.kafka.bootstrap_servers,
                "group.id": "edu-api-sse",
                "client.id": "edu-api-sse",
                "auto.offset.reset": "latest",
                "enable.auto.commit": True,
            }
        )
        consumer.subscribe(_TOPICS)
        backoff = 1.0
        try:
            while not self._stop.is_set():
                try:
                    message = consumer.poll(1.0)
                except Exception as exc:
                    log.warning("sse bridge poll failed; retrying", error=str(exc))
                    self._stop.wait(backoff)
                    backoff = min(30.0, backoff * 2)
                    continue
                if message is None:
                    backoff = 1.0
                    continue
                if message.error():
                    log.warning("sse bridge kafka error", error=str(message.error()))
                    self._stop.wait(backoff)
                    backoff = min(30.0, backoff * 2)
                    continue
                backoff = 1.0
                value, topic = message.value(), message.topic()
                if value is None or topic is None:
                    continue
                try:
                    payload = self._codec.decode(value, schema_subject=topic)
                except Exception:
                    log.warning("sse bridge skipped undecodable message", topic=topic)
                    continue
                self._publish(topic, payload)
        except Exception as exc:
            log.warning("sse bridge stopped", error=str(exc))
        finally:
            consumer.close()

    def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == Topic.NOTIFICATION_DISPATCHED.value:
            self._broadcaster.publish(
                "notification",
                {
                    "recipient_id": payload.get("recipient_id"),
                    "channel": payload.get("channel"),
                    "notification_id": payload.get("aggregate_id"),
                },
            )
        elif topic == Topic.SUBMISSION_GRADED.value:
            self._broadcaster.publish(
                "submission.graded",
                {
                    "submission_id": payload.get("aggregate_id"),
                    "learner_id": payload.get("learner_id"),
                    "assignment_id": payload.get("assignment_id"),
                    "pass_rate": payload.get("pass_rate"),
                },
            )
