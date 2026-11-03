"""BR7/BR8 live overlays: Redis adapter semantics, live score = domain score, producer."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from edu_platform.contexts.analytics.domain.engagement_policy import EngagementPolicy, verb_weights
from edu_platform.contexts.analytics.domain.model import EngagementWeights
from edu_platform.contexts.analytics.infrastructure.redis_live_overlay import (
    TTL_SECONDS,
    RedisLiveOverlay,
)
from edu_platform.contexts.telemetry.domain.events import RawEvent, SchemaVersion
from edu_platform.contexts.telemetry.infrastructure.spark_normalizer import build_use_case
from edu_platform.demo import seed
from edu_platform.demo.live_telemetry import HOTSPOT, generate
from edu_platform.shared_kernel.domain import DomainError
from edu_platform.shared_kernel.domain.ids import LearnerId

fakeredis = pytest.importorskip("fakeredis")
D1, D2 = date(2026, 11, 2), date(2026, 11, 3)


@pytest.fixture
def overlay() -> RedisLiveOverlay:
    return RedisLiveOverlay(fakeredis.FakeRedis(decode_responses=True))


def test_heatmap_writes_are_absolute_and_replay_safe(overlay: RedisLiveOverlay) -> None:
    rows = [(D1, "v-sql-joins", 10, 3, 1, 2, 2), (D1, "v-sql-joins", 11, 1, 0, 0, 1)]
    overlay.write_heatmap(rows)
    overlay.write_heatmap(rows)  # replayed micro-batch
    overlay.write_heatmap([(D1, "v-sql-joins", 10, 4, 1, 2, 3)])  # updated total
    live = overlay.heatmap("v-sql-joins", [D1])
    assert [(s.second, s.play, s.pause, s.seek, s.learners) for s in live.seconds] == [
        (10, 4, 1, 2, 3),
        (11, 1, 0, 0, 1),
    ]
    assert live.days == [D1] and live.updated_at is not None


def test_heatmap_sums_days_and_keeps_max_learners(overlay: RedisLiveOverlay) -> None:
    overlay.write_heatmap([(D1, "v", 5, 1, 1, 0, 4), (D2, "v", 5, 2, 0, 1, 3)])
    live = overlay.heatmap("v", [D1, D2, date(2026, 11, 4)])
    assert [(s.play, s.pause, s.seek, s.learners) for s in live.seconds] == [(3, 1, 1, 4)]
    assert live.days == [D1, D2]  # a day without data does not count as contributing
    assert overlay.heatmap("other", [D1]).seconds == []


def test_engagement_and_ttl(overlay: RedisLiveOverlay) -> None:
    overlay.write_engagement([(D1, "c-sql-101", "p1", 3.0), (D1, "c-sql-101", "p2", 1.256)])
    overlay.write_engagement([(D1, "c-sql-101", "p1", 5.0)])
    live = overlay.engagement("c-sql-101", D1)
    assert live.scores == {"p1": 5.0, "p2": 1.26}
    assert overlay.engagement("c-sql-101", D2).scores == {}
    client = overlay._client
    assert 0 < client.ttl("edu:live:engagement:c-sql-101:2026-11-02") <= TTL_SECONDS


def test_live_score_expression_matches_the_domain_policy() -> None:
    """The streaming CASE expression and EngagementPolicy.score must give the same points."""
    from edu_platform.entrypoints.streaming.engagement_trend_job import score_expression

    weights = EngagementWeights()
    expr = score_expression(weights)
    for verb, weight in verb_weights(weights).items():
        assert f"WHEN '{verb}' THEN {weight}" in expr
        assert EngagementPolicy(weights).score({verb: 1}) == weight
    assert EngagementPolicy(weights).score({"paused": 3, "seeked": 2}) == 0  # not in the CASE
    assert "'paused'" not in expr and expr.endswith("ELSE 0.0 END")


def test_producer_sessions_exercise_hotspot_and_data_quality() -> None:
    now = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    events = generate(200, seed_value=7, now=now)
    assert events == generate(200, seed_value=7, now=now)  # deterministic with a seed
    use_case = build_use_case(b"secret")
    accepted, rejected = [], []
    for e in events:
        try:
            accepted.append(
                use_case.normalize_one(
                    RawEvent(
                        event_id=e["event_id"],
                        raw_learner_id=LearnerId(e["learner_id"]),
                        schema_version=SchemaVersion.parse(e["schema_version"]),
                        payload=e,
                        received_at=now + timedelta(minutes=5),
                        source_topic="t",
                        partition=0,
                        offset=0,
                    )
                )
            )
        except DomainError:
            rejected.append(e)
    versions = Counter(e["schema_version"] for e in events)
    assert versions["1.0"] > 0 and versions["1.1"] > 0
    assert rejected and all(e["verb"] == "teleported" for e in rejected)
    assert all("email" not in a.extensions for a in accepted)
    assert any(a.is_late for a in accepted)
    # pauses cluster around the hotspot (40 % of each video)
    durations = {ls.content_id: ls.duration_sec for c in seed.COURSES for ls in c.lessons}
    pauses = [a for a in accepted if a.verb.value == "paused"]
    near = [
        a for a in pauses
        if abs(a.video_position.second - HOTSPOT * durations[a.content_id]) <= 10  # type: ignore[union-attr]
    ]  # fmt: skip
    assert pauses and len(near) == len(pauses)


def test_generated_sessions_never_run_past_now_except_skewed_clocks() -> None:
    now = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    events = generate(300, seed_value=3, now=now)
    future = [
        e for e in events if "occurred_at" in e and datetime.fromisoformat(e["occurred_at"]) > now
    ]
    assert future and all(e["platform"] != "web" for e in future)  # only the skewed-device case
    assert all(
        datetime.fromisoformat(e["occurred_at"]) - now <= timedelta(minutes=10) for e in future
    )


def test_clock_skew_is_pinned_to_ingestion_time() -> None:
    use_case = build_use_case(b"secret")
    received = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)

    def normalize(occurred: datetime) -> Any:
        payload = {
            "event_id": "e1", "schema_version": "1.1", "learner_id": "l-001",
            "course_id": "c-sql-101", "session_id": "s", "verb": "played",
            "platform": "ios", "occurred_at": occurred.isoformat(),
        }  # fmt: skip
        raw = RawEvent("e1", LearnerId("l-001"), SchemaVersion(1, 1), payload, received, "t", 0, 0)
        return use_case.normalize_one(raw)

    ahead = normalize(received + timedelta(minutes=10))
    assert ahead.occurred_at == received
    assert ahead.extensions["clock_skew_sec"] == 600.0
    small = normalize(received + timedelta(seconds=90))  # within tolerance: untouched
    assert small.occurred_at == received + timedelta(seconds=90)
    assert "clock_skew_sec" not in small.extensions
