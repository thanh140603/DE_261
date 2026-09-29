"""Generic Kafka consumer loop used by long-running services (not by Flink jobs).

Content (TODO):
- confluent_kafka.Consumer with manual commit (enable.auto.commit=false).
- ``run(handler)``: poll -> decode -> handler(message) -> commit; after N
  handler failures forward the record to ``<topic>.dlq`` and commit (poison-pill guard).
- Graceful shutdown on SIGTERM (finish in-flight record, commit, close).
- Expose lag / processed / failed counters for Prometheus.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class KafkaConsumerLoop:
    def __init__(self, bootstrap_servers: str, group_id: str, topics: list[str]) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._topics = topics

    def run(self, handler: Callable[[dict[str, Any]], None]) -> None:
        raise NotImplementedError  # TODO: poll loop described above
