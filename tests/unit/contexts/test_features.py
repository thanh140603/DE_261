from __future__ import annotations

from datetime import UTC, datetime, timedelta

import fakeredis

from edu_platform.contexts.recommendation.application.compute_session_features import (
    SessionFeaturePolicy,
)
from edu_platform.contexts.recommendation.application.load_learner_features import (
    LoadLearnerFeatures,
)
from edu_platform.contexts.recommendation.domain.model import LongTermFeatures
from edu_platform.contexts.recommendation.domain.next_step_policy import (
    CourseRef,
    FeatureContext,
    NextStepPolicy,
)
from edu_platform.contexts.recommendation.infrastructure.redis_online_store import (
    RedisOnlineFeatureStore,
)
from edu_platform.contexts.telemetry.domain.events import (
    CURRENT_SCHEMA_VERSION,
    LearningEvent,
    Platform,
    Verb,
    VideoPosition,
)
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId, SessionId


def _event(at: datetime, verb: Verb = Verb.VIEWED, session: str = "s1") -> LearningEvent:
    return LearningEvent(
        event_id=f"e-{at.isoformat()}-{verb.value}",
        schema_version=CURRENT_SCHEMA_VERSION,
        learner_pseudonym="k1_abc",
        course_id=CourseId("c-py-201"),
        content_id=ContentId("v-py-func"),
        session_id=SessionId(session),
        verb=verb,
        platform=Platform.WEB,
        occurred_at=at,
        received_at=at,
        video_position=VideoPosition(10),
    )


def test_session_policy_splits_on_30_minute_gap() -> None:
    start = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    events = [
        _event(start),
        _event(start + timedelta(minutes=10), Verb.PAUSED),
        _event(start + timedelta(minutes=45), Verb.SEEKED),
    ]
    policy = SessionFeaturePolicy()
    sessions = policy.split(events)
    assert len(sessions) == 2
    assert [e.session_id for e in sessions[0]] == ["s1", "s1"]


def test_session_policy_computes_features_and_struggle() -> None:
    start = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    events = [
        _event(start, Verb.SEEKED),
        _event(start + timedelta(minutes=5), Verb.SEEKED),
        _event(start + timedelta(minutes=10), Verb.ATTEMPTED),
    ]
    features = SessionFeaturePolicy().compute(events)
    assert features is not None
    assert features.events_in_session == 3
    assert features.active_minutes == 10.0
    assert features.last_verbs == ("seeked", "seeked", "attempted")
    assert features.struggle_score == 0.65
    assert features.current_course_id == "c-py-201"


def test_feature_context_low_pass_rate_demotes_next_step() -> None:
    catalogue = [
        CourseRef("e1", "Easy one", "easy", "database"),
        CourseRef("m1", "Medium one", "medium", "database"),
        CourseRef("e2", "Easy two", "easy", "analytics"),
    ]
    policy = NextStepPolicy()
    base = policy.suggest_courses(catalogue, ["e1"], ["e1"])
    assert base[0].course_id == "m1"
    low = LongTermFeatures(
        learner_pseudonym="k1_abc",
        completion_rate_30d=0.5,
        avg_pass_rate_30d=0.2,
        active_days_30d=2,
        preferred_platform="web",
        skill_mastery={},
        computed_at=datetime.now(tz=UTC),
    )
    gated = policy.suggest_courses(catalogue, ["e1"], ["e1"], FeatureContext(longterm=low))
    assert gated[0].course_id == "e2"


def test_feature_store_round_trip_and_join() -> None:
    store = RedisOnlineFeatureStore(fakeredis.FakeRedis(decode_responses=True))
    longterm = LongTermFeatures(
        learner_pseudonym="k1_abc",
        completion_rate_30d=0.7,
        avg_pass_rate_30d=0.8,
        active_days_30d=10,
        preferred_platform="web",
        skill_mastery={"python": 0.9},
        computed_at=datetime(2026, 11, 1, tzinfo=UTC),
    )
    start = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    session = SessionFeaturePolicy().compute([_event(start, Verb.SEEKED)])
    assert session is not None
    store.put_longterm(longterm)
    store.put_session(session)
    joined = LoadLearnerFeatures(store).execute("k1_abc")
    assert joined.longterm is not None and joined.longterm.avg_pass_rate_30d == 0.8
    assert joined.session is not None and joined.session.events_in_session == 1
    assert store.count() == 1
    assert store.count_sessions() == 1


def test_session_policy_advances_incrementally() -> None:
    start = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    policy = SessionFeaturePolicy()
    first = policy.advance(None, _event(start, Verb.SEEKED))
    second = policy.advance(first, _event(start + timedelta(minutes=5), Verb.ATTEMPTED))
    assert second.events_in_session == 2
    assert second.active_minutes == 5.0
    assert second.struggle_score == 0.4
    assert second.started_at == start
    third = policy.advance(second, _event(start + timedelta(minutes=40), Verb.VIEWED))
    assert third.events_in_session == 1
    assert third.session_id == "s1"


def test_features_online_write_partition_materialises_rows() -> None:
    from edu_platform.entrypoints.batch.features_online_job import write_partition

    store = RedisOnlineFeatureStore(fakeredis.FakeRedis(decode_responses=True))
    write_partition(
        [
            {
                "learner_pseudonym": "k1_abc",
                "completion_rate_30d": 0.5,
                "avg_pass_rate_30d": 0.75,
                "active_days_30d": 7,
                "preferred_platform": "web",
                "skill_mastery": {"python": 0.9},
                "computed_at": datetime(2026, 11, 1, tzinfo=UTC),
            }
        ],
        "redis://unused",
        store=store,
    )
    restored = store.get_longterm("k1_abc")
    assert restored is not None and restored.avg_pass_rate_30d == 0.75
