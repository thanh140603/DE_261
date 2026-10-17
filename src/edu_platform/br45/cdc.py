"""Genuine Debezium landing: immutable raw log, validated current rows and durable outbox."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from confluent_kafka import Consumer, Producer
from psycopg.types.json import Jsonb

from .config import AnalyticsSettings, settings
from .contracts import CONTRACTS, identity, row_key, timestamp, validate_row
from .db import Db, clean, connect, state

log = logging.getLogger(__name__)


def emit(
    conn: Db, event_id: str, student_id: str, course_id: str, at: datetime, delta: int, kind: str
) -> None:
    payload = {
        "event_id": event_id,
        "student_id": student_id,
        "course_id": course_id,
        "event_time": at.isoformat(),
        "delta": delta,
        "kind": kind,
    }
    conn.execute(
        "INSERT INTO analytics.outbox(event_id,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING",
        (event_id, Jsonb(payload)),
    )


def tick(conn: Db, at: datetime, cfg: AnalyticsSettings) -> None:
    # Window ends are UTC epoch-aligned. A tick at boundary T closes [T-7d,T).
    at = datetime.fromtimestamp(int(at.timestamp()) // cfg.slide_seconds * cfg.slide_seconds, UTC)
    previous = state(conn, "evaluation_clock")
    if previous and timestamp(previous) > at:
        return
    state(conn, "evaluation_clock", at.isoformat())
    for en in clean(conn, "enrollments"):
        if en["status"] == "active" and timestamp(en["enrolled_at"]) <= at:
            # T-1ms includes the window ending at T, without including future activity.
            emit(
                conn,
                identity("tick", en["id"], at.isoformat()),
                en["student_id"],
                en["course_id"],
                at - timedelta(milliseconds=1),
                0,
                "clock",
            )


def ingest(
    conn: Db,
    topic: str,
    partition: int,
    offset: int,
    value: dict[str, Any] | None,
    cfg: AnalyticsSettings | None = None,
) -> str:
    cfg = cfg or settings()
    envelope = value.get("payload", value) if isinstance(value, dict) else value
    if not envelope:
        return "tombstone"
    envelope = envelope if isinstance(envelope, dict) else {"malformed": envelope}
    source = envelope.get("source") or {}
    source = source if isinstance(source, dict) else {}
    table = source.get("table", topic.rsplit(".", 1)[-1])
    op = envelope.get("op")
    row = envelope.get("before") if op == "d" else envelope.get("after")
    change_id = identity(table, source.get("lsn"), source.get("txId"), op, row)
    inserted = conn.execute(
        (
            "INSERT INTO "
            "analytics.raw_changes(topic,partition,offset_id,change_id,envelope) "
            "VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING change_id"
        ),
        (topic, partition, offset, change_id, Jsonb(value)),
    ).fetchone()
    if not inserted:
        return "duplicate"
    try:
        if table not in CONTRACTS or op not in {"c", "r", "u", "d"} or not row:
            raise ValueError("unsupported table/operation or missing row image")
        if not isinstance(row, dict):
            raise ValueError("row image must be an object")
        data = validate_row(table, row)
        key = row_key(table, data)
        lsn = int(source.get("lsn") or 0)
        old = conn.execute(
            "SELECT * FROM analytics.clean_rows WHERE table_name=%s AND row_key=%s FOR UPDATE",
            (table, key),
        ).fetchone()
        if old and old["lsn"] >= lsn:
            return "stale"
        old_data = old["data"] if old and not old["deleted"] else None
        if table == "activity_events":
            # Older-than-watermark corrections cannot safely retract evicted Spark state.
            watermark = state(conn, "stream_watermark")
            affected = ([old_data] if old_data else []) + ([data] if op != "d" else [])
            if watermark and any(
                timestamp(r["event_time"]) <= timestamp(watermark) for r in affected
            ):
                raise ValueError(
                    "activity mutation is older than the supported watermark; requires controlled"
                    " backfill"
                )
            clock = state(conn, "evaluation_clock")
            if clock and timestamp(data["event_time"]) > timestamp(clock) + timedelta(
                seconds=cfg.slide_seconds
            ):
                raise ValueError("activity event is ahead of the evaluation clock")
        conn.execute(
            (
                "INSERT INTO analytics.clean_rows(table_name,row_key,data,lsn,deleted) "
                "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(table_name,row_key) DO UPDATE SET "
                "data=excluded.data,lsn=excluded.lsn,deleted=excluded.deleted"
            ),
            (table, key, Jsonb(data), lsn, op == "d"),
        )
        if table == "activity_events":
            if old_data:
                emit(
                    conn,
                    identity(change_id, "before"),
                    old_data["student_id"],
                    old_data["course_id"],
                    timestamp(old_data["event_time"]),
                    -1,
                    "activity",
                )
            if op != "d":
                emit(
                    conn,
                    identity(change_id, "after"),
                    data["student_id"],
                    data["course_id"],
                    timestamp(data["event_time"]),
                    1,
                    "activity",
                )
        if table == "clocks" and op != "d":
            tick(conn, timestamp(data["evaluated_at"]), cfg)
        if table in {
            "courses",
            "assignments",
            "questions",
            "test_cases",
            "submissions",
            "evaluations",
        }:
            state(conn, "assessment_source_revision", change_id)
        state(conn, "source_revision", change_id)
        return "processed"
    except (ValueError, KeyError, TypeError) as exc:
        conn.execute(
            (
                "INSERT INTO analytics.quarantine(change_id,reason,payload) VALUES(%s,%s,%s) "
                "ON CONFLICT DO NOTHING"
            ),
            (change_id, str(exc), Jsonb(value)),
        )
        log.warning("quarantined change %s: %s", change_id, exc)
        return "invalid"


def publish_outbox(conn: Db, producer: Producer, cfg: AnalyticsSettings) -> int:
    rows = list(
        conn.execute(
            "SELECT event_id,payload FROM analytics.outbox WHERE published_at IS NULL "
            "ORDER BY created_at,event_id LIMIT 2000 FOR UPDATE SKIP LOCKED"
        )
    )
    errors = []
    published = state(conn, "published_offsets") or {}

    def delivered(err: Any, _msg: Any) -> Any:
        if err:
            errors.append(str(err))
        else:
            key = str(_msg.partition())
            published[key] = max(published.get(key, 0), _msg.offset() + 1)

    for r in rows:
        producer.produce(
            cfg.activity_topic,
            key=r["payload"]["student_id"] + ":" + r["payload"]["course_id"],
            value=json.dumps(r["payload"]),
            on_delivery=delivered,
        )
    remaining = producer.flush(30)
    if errors or remaining:
        raise RuntimeError(f"outbox publish failed: {errors}; pending={remaining}")
    for r in rows:
        conn.execute(
            "UPDATE analytics.outbox SET published_at=now() WHERE event_id=%s", (r["event_id"],)
        )
    if rows:
        state(conn, "published_offsets", published)
    return len(rows)


def run() -> None:
    from .assessment import refresh

    cfg = settings()
    consumer = Consumer(
        {
            "bootstrap.servers": cfg.kafka,
            "group.id": "br45-landing-v1",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "max.poll.interval.ms": 300000,
        }
    )
    producer = Producer({"bootstrap.servers": cfg.kafka, "enable.idempotence": True})
    consumer.subscribe([cfg.topic_prefix + t for t in CONTRACTS])
    logging.basicConfig(level=logging.INFO)
    last_wall_tick = None
    try:
        while True:
            messages = consumer.consume(num_messages=5000, timeout=1)
            with connect() as conn:
                counts: dict[str, int] = {}
                for msg in messages:
                    if msg.error():
                        raise RuntimeError(str(msg.error()))
                    raw = msg.value()
                    try:
                        payload = json.loads(raw) if raw else None
                    except (ValueError, UnicodeDecodeError):
                        payload = {"invalid_json": (raw or b"").decode(errors="replace")}
                    topic, partition, offset = msg.topic(), msg.partition(), msg.offset()
                    assert topic is not None and partition is not None and offset is not None
                    status = ingest(conn, topic, partition, offset, payload, cfg)
                    counts[status] = counts.get(status, 0) + 1
                if cfg.clock_mode == "wall":
                    current = datetime.now(UTC)
                    boundary = int(current.timestamp()) // cfg.slide_seconds
                    if boundary != last_wall_tick:
                        tick(conn, current, cfg)
                        last_wall_tick = boundary
                at = state(conn, "evaluation_clock")
                if messages and at and counts.get("processed", 0):
                    revision = state(conn, "source_revision")
                    for en in clean(conn, "enrollments"):
                        if en["status"] == "active":
                            emit(
                                conn,
                                identity(revision, en["id"], "refresh"),
                                en["student_id"],
                                en["course_id"],
                                timestamp(at) - timedelta(milliseconds=1),
                                0,
                                "metadata",
                            )
                if messages and at:
                    refresh(conn, timestamp(at) - timedelta(days=30), timestamp(at), cfg=cfg)
                if messages:
                    state(
                        conn,
                        "landing",
                        {
                            "counts": counts,
                            "last_success_at": datetime.now(UTC).isoformat(),
                            "last_offsets": {m.topic(): m.offset() for m in messages},
                        },
                    )
                    log.info("CDC batch: %s", counts)
            # Publish only after raw/clean/outbox commit, so Spark cannot observe a
            # window delta whose operational metadata is still uncommitted.
            with connect() as conn:
                publish_outbox(conn, producer, cfg)
            # DB commit precedes Kafka offset commit. A crash in between safely replays raw keys.
            if messages:
                consumer.commit(asynchronous=False)
    finally:
        consumer.close()
