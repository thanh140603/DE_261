"""Kafka topic administration from the topic catalogue (infra/kafka/topics.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def topic_specs(
    catalogue: dict[str, Any], replication_factor: int | None = None
) -> list[dict[str, Any]]:
    """Resolve each topic against the catalogue defaults (pure, unit-tested)."""
    defaults = catalogue.get("defaults", {})
    specs = []
    for topic in catalogue.get("topics", []):
        specs.append(
            {
                "name": topic["name"],
                "partitions": int(topic.get("partitions", defaults.get("partitions", 1))),
                "replication_factor": int(
                    replication_factor
                    or topic.get("replication_factor")
                    or defaults.get("replication_factor", 1)
                ),
                "config": {
                    k: str(v)
                    for k, v in {**defaults.get("config", {}), **topic.get("config", {})}.items()
                },
            }
        )
    return specs


def create_topics_from_file(
    path: str,
    bootstrap_servers: str,
    replication_factor: int | None = None,
    only: set[str] | None = None,
) -> list[str]:
    """Create missing topics (all, or the catalogue entries named in ``only``); returns the
    names actually created. A topic created concurrently by someone else is not an error."""
    from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]

    catalogue = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    existing = set(admin.list_topics(timeout=10).topics)
    new = [
        NewTopic(s["name"], s["partitions"], s["replication_factor"], config=s["config"])
        for s in topic_specs(catalogue, replication_factor)
        if s["name"] not in existing and (only is None or s["name"] in only)
    ]
    if not new:
        return []
    from confluent_kafka import KafkaError, KafkaException

    created = []
    for topic, future in admin.create_topics(new).items():
        try:
            future.result()
            created.append(topic)
        except KafkaException as exc:
            if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                raise
    return created
