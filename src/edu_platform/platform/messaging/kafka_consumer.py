"""Generic Kafka consumer loop used by long-running services (not Flink jobs).

Manual-commit loop with a poison-pill guard: a record whose handler keeps
failing is forwarded to ``<topic>.dlq`` and committed so the group does not
stall. SIGTERM/SIGINT drain the in-flight record and close cleanly.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from edu_platform.platform.logging import get_logger
from edu_platform.platform.serialization.codec import JsonCodec

log = get_logger(__name__)


@dataclass(frozen=True)
class KafkaMessage:
    topic: str
    key: str | None
    payload: dict[str, Any]
    partition: int
    offset: int


class KafkaConsumerLoop:
    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        topics: list[str],
        *,
        codec: JsonCodec | None = None,
        dlq_publisher: Callable[[str, dict[str, Any]], None] | None = None,
        max_retries: int = 3,
        resilient: bool = False,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._topics = topics
        self._codec = codec or JsonCodec()
        self._dlq_publisher = dlq_publisher
        self._max_retries = max_retries
        # BR1/3 opt in: a broker that is still starting must not crash-loop the
        # service. BR8/content-sync keeps the original fail-fast behaviour.
        self._resilient = resilient

    def _build(self) -> Any:
        from confluent_kafka import Consumer

        return Consumer(
            {
                "bootstrap.servers": self._bootstrap_servers,
                "group.id": self._group_id,
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
            }
        )

    def run(self, handler: Callable[[KafkaMessage], None]) -> None:
        consumer = self._build()
        consumer.subscribe(self._topics)
        running = True

        def _stop(_signum: int, _frame: Any) -> None:
            nonlocal running
            running = False

        previous_handlers = {
            sig: signal.signal(sig, _stop) for sig in (signal.SIGTERM, signal.SIGINT)
        }
        backoff = 1.0
        try:
            while running:
                try:
                    message = consumer.poll(1.0)
                    if message is None:
                        backoff = 1.0
                        continue
                    if message.error():
                        from confluent_kafka import KafkaError, KafkaException

                        if message.error().code() == KafkaError._PARTITION_EOF:
                            continue
                        raise KafkaException(message.error())
                    payload = self._codec.decode(message.value(), schema_subject=message.topic())
                    failures = 0
                    while True:
                        try:
                            handler(
                                KafkaMessage(
                                    topic=message.topic(),
                                    key=_text(message.key()),
                                    payload=payload,
                                    partition=message.partition(),
                                    offset=message.offset(),
                                )
                            )
                            break
                        except Exception:
                            failures += 1
                            if failures >= self._max_retries:
                                if self._dlq_publisher is not None:
                                    self._dlq_publisher(f"{message.topic()}.dlq", payload)
                                break
                    consumer.commit(asynchronous=False)
                    backoff = 1.0
                except Exception as exc:
                    # BR1/3 opt in: survive a broker that is still starting up or a
                    # topic that has not been created yet (UNKNOWN_TOPIC_OR_PART).
                    # Other consumers (BR8 content-sync) keep the original fail-fast
                    # behaviour so their orchestration/restart semantics do not change.
                    if not running:
                        break
                    if not self._resilient:
                        raise
                    log.warning(
                        "kafka consumer poll failed; retrying",
                        group_id=self._group_id,
                        error=str(exc),
                        retry_in_seconds=backoff,
                    )
                    time.sleep(backoff)
                    backoff = min(30.0, backoff * 2)
        finally:
            consumer.close()
            for sig, previous in previous_handlers.items():
                signal.signal(sig, previous)


def _text(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
