from __future__ import annotations

from datetime import UTC, datetime, timedelta

from edu_platform.contexts.analytics.application.build_video_heatmap import BuildVideoHeatmap
from edu_platform.contexts.analytics.domain.anomaly_policy import AssessmentAnomalyPolicy
from edu_platform.contexts.analytics.domain.engagement_policy import EngagementPolicy
from edu_platform.contexts.analytics.domain.model import AnomalyThreshold, EngagementWeights
from edu_platform.contexts.content.domain.chunking import SemanticChunker
from edu_platform.contexts.content.domain.model import ChunkingStrategy
from edu_platform.contexts.risk.domain.model import RiskSignal, SignalKind
from edu_platform.contexts.risk.domain.scoring_policy import RiskScoringPolicy
from edu_platform.contexts.telemetry.domain.events import (
    CURRENT_SCHEMA_VERSION,
    LearningEvent,
    Platform,
    Verb,
    VideoPosition,
)
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId, SessionId

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def test_anomaly_policy_needs_volume_and_gap() -> None:
    policy = AssessmentAnomalyPolicy(AnomalyThreshold(min_attempts=10))
    assert policy.is_anomalous(attempts=12, pass_rate=0.0, median=0.9)
    assert not policy.is_anomalous(attempts=5, pass_rate=0.0, median=0.9)
    assert not policy.is_anomalous(attempts=50, pass_rate=0.3, median=0.4)


def test_engagement_decline_needs_two_consecutive_drops() -> None:
    policy = EngagementPolicy(EngagementWeights())
    assert policy.score({"viewed": 2, "attempted": 1, "posted": 1}) == 5.5
    assert policy.is_declining([10, 6, 3])
    assert not policy.is_declining([10, 6, 8])
    assert not policy.is_declining([10, 9])


def test_risk_score_saturates_and_decays() -> None:
    policy = RiskScoringPolicy(half_life=timedelta(days=7))
    fresh = [
        RiskSignal(SignalKind.DEADLINE_MISSED, 0.5, NOW),
        RiskSignal(SignalKind.LOGIN_GAP, 0.5, NOW),
    ]
    assert policy.score(fresh, NOW).value == 0.75
    old = [RiskSignal(SignalKind.DEADLINE_MISSED, 0.5, NOW - timedelta(days=7))]
    assert policy.score(old, NOW).value == 0.25
    assert policy.score([], NOW).value == 0.0


def _event(verb: Verb, second: int, learner: str = "p1") -> LearningEvent:
    return LearningEvent(
        event_id=f"{verb}-{second}-{learner}",
        schema_version=CURRENT_SCHEMA_VERSION,
        learner_pseudonym=learner,
        course_id=CourseId("c"),
        content_id=ContentId("v1"),
        session_id=SessionId("s"),
        verb=verb,
        platform=Platform.WEB,
        occurred_at=NOW,
        received_at=NOW,
        video_position=VideoPosition(second),
    )


def test_heatmap_buckets_per_second() -> None:
    events = [_event(Verb.SEEKED, 3), _event(Verb.SEEKED, 3, "p2"), _event(Verb.PLAYED, 999)]
    buckets = BuildVideoHeatmap().execute(events, ContentId("v1"), duration_sec=5)
    assert len(buckets) == 5
    assert (buckets[3].seek_count, buckets[3].unique_learners) == (2, 2)
    assert buckets[4].play_count == 1, "positions past the end clamp to the last second"


def test_semantic_chunker_respects_headings() -> None:
    text = "# Intro\n\n" + ("word " * 30) + "\n\n# Details\n\n" + ("more " * 30)
    chunks = SemanticChunker().chunk(
        ContentId("c"), 1, text, ChunkingStrategy(max_tokens=40, min_chunk_tokens=5)
    )
    assert [c.section_path for c in chunks] == [("Intro",), ("Details",)]
    assert all(c.ordinal == i for i, c in enumerate(chunks))
