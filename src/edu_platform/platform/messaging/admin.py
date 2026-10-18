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
    path: str, bootstrap_servers: str, replication_factor: int | None = None
) -> list[str]:
    """Create missing topics; returns the names actually created."""
    from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]

    catalogue = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    existing = set(admin.list_topics(timeout=10).topics)
    new = [
        NewTopic(s["name"], s["partitions"], s["replication_factor"], config=s["config"])
        for s in topic_specs(catalogue, replication_factor)
        if s["name"] not in existing
    ]
    if not new:
        return []
    for future in admin.create_topics(new).values():
        future.result()  # raises on failure
    return [t.topic for t in new]
