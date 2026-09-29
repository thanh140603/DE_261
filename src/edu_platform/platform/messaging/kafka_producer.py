"""Kafka adapter implementing the shared ``EventPublisher`` port.

Content (TODO):
- Wrap confluent_kafka.Producer with idempotence enabled (enable.idempotence=true, acks=all).
- Key every message by ``event.aggregate_id`` to preserve per-aggregate ordering.
- Encode payload via platform.serialization (JSON now, Avro + Schema Registry later).
- Add headers: event_type, event_id, schema_version, trace_id.
- Route to ``topic`` argument or derive from event_type via a registry map.
- Flush on close; expose delivery-report callback for metrics.
"""

from __future__ import annotations

from edu_platform.shared_kernel.domain.event import DomainEvent


class KafkaEventPublisher:
    def __init__(self, bootstrap_servers: str, *, client_id: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        # TODO: instantiate confluent_kafka.Producer lazily.

    def publish(self, events: list[DomainEvent], *, topic: str | None = None) -> None:
        raise NotImplementedError  # TODO: see module docstring

    def close(self) -> None:
        raise NotImplementedError  # TODO: flush with bounded timeout
