"""Transactional domain events. Each record is retryable and has a stable identity."""

from __future__ import annotations

import json
from typing import Any

from psycopg.types.json import Jsonb

from .config import AnalyticsSettings
from .contracts import identity
from .db import Db


def enqueue(conn: Db, topic: str, key: str, payload: dict[str, Any]) -> int:
    event_id = payload.get("event_id") or identity(topic, key, payload)
    row = conn.execute(
        "INSERT INTO analytics.domain_outbox(event_id,topic,event_key,payload) "
        "VALUES(%s,%s,%s,%s) ON CONFLICT(event_id) DO UPDATE SET event_id=excluded.event_id "
        "RETURNING sequence",
        (event_id, topic, key, Jsonb({**payload, "event_id": event_id})),
    ).fetchone()
    assert row is not None
    return int(row["sequence"])


def alert_transition(conn: Db, cfg: AnalyticsSettings, alert: dict[str, Any], actor: str) -> None:
    status = alert["status"]
    at = alert["resolved_at"] or alert["acknowledged_at"] or alert["created_at"]
    learner, course = alert["student_id"], alert["course_id"]
    common = {
        "alert_id": alert["id"],
        "learner_id": learner,
        "course_id": course,
        "score": alert["score"] / 100,
        "occurred_at": at.isoformat(),
        "top_signals": [r["signal"] for r in alert["reasons"]],
        "status": status,
        "policy_version": alert["policy_version"],
        "actor": actor,
    }
    enqueue(conn, cfg.domain_topic, f"{learner}:{course}", {"kind": "alert_transition", **common})
    if cfg.mode == "persistent" and not cfg.engine_benchmark:
        enqueue(conn, "risk.alert_transition.v1", f"{learner}:{course}", common)
        if status == "NEW":
            enqueue(conn, "risk.dropout_alert.v1", f"{learner}:{course}", common)


def publish(conn: Db, producer: Any) -> int:
    rows = list(
        conn.execute(
            "SELECT * FROM analytics.domain_outbox WHERE published_at IS NULL "
            "ORDER BY sequence LIMIT 2000 FOR UPDATE SKIP LOCKED"
        )
    )
    errors: list[str] = []

    def delivered(error: Any, message: Any) -> None:
        if error:
            errors.append(str(error))

    for row in rows:
        producer.produce(
            row["topic"],
            key=row["event_key"],
            value=json.dumps({**row["payload"], "sequence": row["sequence"]}),
            on_delivery=delivered,
        )
    remaining = producer.flush(30)
    if errors or remaining:
        raise RuntimeError(f"Domain publication failed: {errors}; pending={remaining}")
    if rows:
        conn.execute(
            "UPDATE analytics.domain_outbox SET published_at=now() WHERE event_id=ANY(%s)",
            ([r["event_id"] for r in rows],),
        )
    return len(rows)
