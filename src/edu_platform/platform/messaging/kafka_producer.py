"""Kafka adapter implementing the shared ``EventPublisher`` port.

Wraps ``confluent_kafka.Producer`` with idempotence enabled, keys every message
by ``aggregate_id`` for per-aggregate ordering, and encodes through the shared
codec. Event types whose topic name differs from the type (risk, content) are
mapped here so domain code never knows about topic routing.
"""

from __future__ import annotations

from typing import Any

from edu_platform.platform.messaging.topics import Topic
from edu_platform.platform.serialization.codec import JsonCodec
from edu_platform.shared_kernel.domain.event import DomainEvent

# Event type -> topic for the handful of types whose topic name differs.
_ROUTES: dict[str, str] = {
    "risk.dropout_risk_detected.v1": Topic.DROPOUT_RISK_ALERT.value,
    "content.version_published.v1": Topic.CONTENT_UPDATED.value,
}


class KafkaEventPublisher:
    def __init__(
        self,
        bootstrap_servers: str,
        *,
        client_id: str,
        codec: JsonCodec | None = None,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        self._codec = codec or JsonCodec()
        self._producer: Any = None

    def _get(self) -> Any:
        if self._producer is None:
            from confluent_kafka import Producer

            self._producer = Producer(
                {
                    "bootstrap.servers": self._bootstrap_servers,
                    "client.id": self._client_id,
                    "enable.idempotence": True,
                    "acks": "all",
                }
            )
        return self._producer

    def publish(self, events: list[DomainEvent], *, topic: str | None = None) -> None:
        for event in events:
            target = topic or _ROUTES.get(event.event_type, event.event_type)
            self.publish_raw(
                target,
                key=event.aggregate_id,
                payload=event.to_payload(),
                headers={"event_type": event.event_type, "event_id": event.event_id},
            )

    def publish_raw(
        self,
        topic: str,
        *,
        key: str | None,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        self._get().produce(
            topic,
            key=key,
            value=self._codec.encode(payload, schema_subject=topic),
            headers=headers or {},
        )

    def close(self) -> None:
        if self._producer is not None:
            self._producer.flush(5)
