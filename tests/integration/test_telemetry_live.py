"""Telemetry fast path + BR7/BR8 live overlays: local Spark against real Kafka and Redis.

  docker compose up -d kafka redis
  uv run pytest -m "spark and integration" tests/integration/test_telemetry_live.py

Parity: the overlays must equal what the domain computes from the same events
(NormalizeEvents + EngagementPolicy / play-pause-seek counts). Replays must not change them.
"""

from __future__ import annotations

import json
import os
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from edu_platform.contexts.analytics.domain.engagement_policy import EngagementPolicy
from edu_platform.contexts.analytics.domain.model import EngagementWeights
from edu_platform.contexts.analytics.infrastructure.redis_live_overlay import RedisLiveOverlay
from edu_platform.contexts.telemetry.domain.events import RawEvent, SchemaVersion
from edu_platform.contexts.telemetry.infrastructure.spark_normalizer import build_use_case
from edu_platform.demo.live_telemetry import generate
from edu_platform.entrypoints.streaming import (
    engagement_trend_job,
    telemetry_normalization_job,
    video_heatmap_job,
)
from edu_platform.shared_kernel.domain import DomainError
from edu_platform.shared_kernel.domain.ids import LearnerId

pytestmark = [pytest.mark.spark, pytest.mark.integration]
KAFKA = os.getenv("EDU_KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
REDIS = os.getenv("EDU_TEST_REDIS_URL", "redis://localhost:6379/15")  # isolated test db
SECRET = b"live-test-secret"
NOW = datetime.now(tz=UTC).replace(microsecond=0)


@pytest.fixture(scope="module")
def topics() -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    return {k: f"test.{k}.{suffix}" for k in ("raw", "events", "dlq")}


@pytest.fixture(scope="module")
def events(topics: dict[str, str]) -> list[dict[str, Any]]:
    pytest.importorskip("confluent_kafka")
    from confluent_kafka import Producer

    producer = Producer({"bootstrap.servers": KAFKA, "socket.timeout.ms": 3000})
    if producer.list_topics(timeout=5) is None:
        pytest.skip(f"Kafka not reachable at {KAFKA}")
    payloads = generate(40, seed_value=11, now=NOW)
    for p in payloads + payloads[:5]:  # 5 client re-sends: dedup must absorb them
        producer.produce(topics["raw"], key=p["learner_id"], value=json.dumps(p).encode())
    assert producer.flush(15) == 0
    return payloads


@pytest.fixture(scope="module")
def overlay() -> Iterator[RedisLiveOverlay]:
    import redis

    client = redis.Redis.from_url(REDIS, decode_responses=True)
    try:
        client.ping()
    except redis.exceptions.ConnectionError:
        pytest.skip(f"Redis not reachable at {REDIS}")
    client.flushdb()
    yield RedisLiveOverlay(client)
    client.flushdb()


@pytest.fixture(scope="module")
def spark(spark_session: Any) -> Any:
    return spark_session


def run_once(spark: Any, topics: dict[str, str], overlay: RedisLiveOverlay, root: Path) -> None:
    telemetry_normalization_job.start(
        spark, SECRET, KAFKA, str(root / "normalize"), once=True,
        raw_topic=topics["raw"], events_topic=topics["events"], dlq_topic=topics["dlq"],
    ).awaitTermination()  # fmt: skip
    for job in (video_heatmap_job, engagement_trend_job):
        job.start(
            spark, KAFKA, overlay, str(root / job.__name__.rsplit(".", 1)[-1]), once=True,
            topic=topics["events"],
        ).awaitTermination()  # fmt: skip


def expected(
    payloads: list[dict[str, Any]],
) -> tuple[dict[Any, Counter[str]], dict[Any, float], int]:
    """What the domain says, computed without Spark from the same raw payloads."""
    use_case = build_use_case(SECRET)
    heat: dict[Any, Counter[str]] = defaultdict(Counter)
    verbs: dict[Any, Counter[str]] = defaultdict(Counter)
    rejected = 0
    for p in payloads:
        try:
            e = use_case.normalize_one(
                RawEvent(p["event_id"], LearnerId(p["learner_id"]),
                         SchemaVersion.parse(p["schema_version"]), p, NOW, "t", 0, 0)
            )  # fmt: skip
        except DomainError:
            rejected += 1
            continue
        day = e.occurred_at.astimezone(UTC).date()
        verbs[(day, e.course_id, e.learner_pseudonym)][e.verb.value] += 1
        if e.content_id and e.video_position and e.verb.value in ("played", "paused", "seeked"):
            heat[(day, e.content_id, e.video_position.second)][e.verb.value] += 1
    policy = EngagementPolicy(EngagementWeights())
    scores = {k: policy.score(dict(v)) for k, v in verbs.items()}
    return heat, scores, rejected


def test_overlays_equal_the_domain_and_survive_replays(
    spark: Any, topics: dict[str, str], events: list[dict[str, Any]],
    overlay: RedisLiveOverlay, tmp_path: Path,
) -> None:  # fmt: skip
    run_once(spark, topics, overlay, tmp_path / "ckpt")
    heat, scores, rejected = expected(events)
    assert len(heat) > 50 and len(scores) > 10  # the assertions below are not vacuous
    resent = events[:5]
    assert any(p["verb"] in ("played", "paused", "seeked") for p in resent)  # dedup matters
    days = sorted({d for d, _, _ in heat} | {d for d, _, _ in scores})

    for content in {c for _, c, _ in heat}:
        live = {s.second: (s.play, s.pause, s.seek) for s in overlay.heatmap(content, days).seconds}
        want: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
        for (_, c, second), counts in heat.items():
            if c == content:
                for i, verb in enumerate(("played", "paused", "seeked")):
                    want[second][i] += counts[verb]
        assert live == {s: tuple(v) for s, v in want.items()}, content

    for (day, course, pseudonym), score in scores.items():
        got = overlay.engagement(course, day).scores.get(pseudonym, 0.0)
        assert got == pytest.approx(score), (course, pseudonym)

    # rejected records reached the DLQ topic, tagged for the bronze landing job
    from confluent_kafka import Consumer

    consumer = Consumer({"bootstrap.servers": KAFKA, "group.id": f"t-{uuid.uuid4()}",
                         "auto.offset.reset": "earliest"})  # fmt: skip
    consumer.subscribe([topics["dlq"]])
    dlq = []
    deadline = datetime.now(tz=UTC) + timedelta(seconds=20)
    while len(dlq) < rejected and datetime.now(tz=UTC) < deadline:
        m = consumer.poll(1.0)
        if m is not None and not m.error():
            dlq.append(json.loads(m.value()))
    consumer.close()
    assert len(dlq) >= rejected > 0
    assert all(d["rejected_by"] == "spark-stream" and "teleported" in d["reason"] for d in dlq)
    assert all(d["payload"]["verb"] == "teleported" for d in dlq)  # payload kept as JSON

    # replay 1: same checkpoints -> nothing new; replay 2: fresh checkpoints re-read the
    # topics from the start -> absolute writes give exactly the same values
    snapshot = _dump(overlay)
    run_once(spark, topics, overlay, tmp_path / "ckpt")
    assert _dump(overlay) == snapshot
    run_once(spark, topics, overlay, tmp_path / "fresh")
    assert _dump(overlay) == snapshot


def _dump(overlay: RedisLiveOverlay) -> dict[str, dict[str, str]]:
    client = overlay._client
    return {k: client.hgetall(k) for k in sorted(client.keys("edu:live:*")) if "status" not in k}
