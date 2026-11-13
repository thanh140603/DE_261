"""Redis online feature store (BR2).

Two branches share one key space, both keyed by learner pseudonym:

  edu:features:longterm:<pseudonym>  JSON, TTL 36 h (batch SLA 24 h + slack)
  edu:features:session:<pseudonym>   JSON, TTL 2 h  (session SLA 30 s)

The API joins them by pseudonym; the lakehouse keeps the point-in-time copy of
``features.learner_longterm``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from edu_platform.contexts.recommendation.domain.model import LongTermFeatures, SessionFeatures
from edu_platform.platform.storage.redis_client import key

LONGTERM_TTL_SECONDS = 36 * 3600
SESSION_TTL_SECONDS = 2 * 3600


def _longterm_key(pseudonym: str) -> str:
    return key("features", "longterm", pseudonym)


def _session_key(pseudonym: str) -> str:
    return key("features", "session", pseudonym)


class RedisOnlineFeatureStore:
    def __init__(
        self,
        client: Any,
        *,
        longterm_ttl: int = LONGTERM_TTL_SECONDS,
        session_ttl: int = SESSION_TTL_SECONDS,
    ) -> None:
        self._client = client
        self._longterm_ttl = longterm_ttl
        self._session_ttl = session_ttl

    def put_longterm(self, features: LongTermFeatures) -> None:
        self._client.set(
            _longterm_key(features.learner_pseudonym),
            json.dumps(_longterm_to_dict(features)),
            ex=self._longterm_ttl,
        )
        index = key("features", "longterm", "index")
        self._client.sadd(index, features.learner_pseudonym)
        self._client.expire(index, self._longterm_ttl)
        self._client.hset(key("features", "meta"), "longterm_at", features.computed_at.isoformat())

    def put_session(self, features: SessionFeatures) -> None:
        self._client.set(
            _session_key(features.learner_pseudonym),
            json.dumps(_session_to_dict(features)),
            ex=self._session_ttl,
        )
        index = key("features", "session", "index")
        self._client.sadd(index, features.learner_pseudonym)
        self._client.expire(index, self._session_ttl)
        self._client.hset(key("features", "meta"), "session_at", features.updated_at.isoformat())

    def get_longterm(self, learner_pseudonym: str) -> LongTermFeatures | None:
        raw = self._client.get(_longterm_key(learner_pseudonym))
        return _longterm_from_dict(json.loads(raw)) if raw is not None else None

    def get_session(self, learner_pseudonym: str) -> SessionFeatures | None:
        raw = self._client.get(_session_key(learner_pseudonym))
        return _session_from_dict(json.loads(raw)) if raw is not None else None

    def count(self) -> int:
        return int(self._client.scard(key("features", "longterm", "index")))

    def count_sessions(self) -> int:
        return int(self._client.scard(key("features", "session", "index")))

    def claim_event(self, event_id: str) -> bool:
        """True the first time this event is seen; makes at-least-once replay idempotent."""
        key_name = key("features", "session", "seen", event_id)
        return bool(self._client.set(key_name, "1", nx=True, ex=3600))


def _longterm_to_dict(features: LongTermFeatures) -> dict[str, Any]:
    return {
        "learner_pseudonym": features.learner_pseudonym,
        "completion_rate_30d": features.completion_rate_30d,
        "avg_pass_rate_30d": features.avg_pass_rate_30d,
        "active_days_30d": features.active_days_30d,
        "preferred_platform": features.preferred_platform,
        "skill_mastery": features.skill_mastery,
        "computed_at": features.computed_at.isoformat(),
    }


def _longterm_from_dict(raw: dict[str, Any]) -> LongTermFeatures:
    return LongTermFeatures(
        learner_pseudonym=str(raw["learner_pseudonym"]),
        completion_rate_30d=float(raw["completion_rate_30d"]),
        avg_pass_rate_30d=float(raw["avg_pass_rate_30d"]),
        active_days_30d=int(raw["active_days_30d"]),
        preferred_platform=str(raw["preferred_platform"]),
        skill_mastery={str(k): float(v) for k, v in (raw.get("skill_mastery") or {}).items()},
        computed_at=datetime.fromisoformat(str(raw["computed_at"])),
    )


def _session_to_dict(features: SessionFeatures) -> dict[str, Any]:
    return {
        "learner_pseudonym": features.learner_pseudonym,
        "session_id": features.session_id,
        "active_minutes": features.active_minutes,
        "events_in_session": features.events_in_session,
        "last_verbs": list(features.last_verbs),
        "current_course_id": features.current_course_id,
        "struggle_score": features.struggle_score,
        "updated_at": features.updated_at.isoformat(),
        "started_at": features.started_at.isoformat() if features.started_at else None,
    }


def _session_from_dict(raw: dict[str, Any]) -> SessionFeatures:
    return SessionFeatures(
        learner_pseudonym=str(raw["learner_pseudonym"]),
        session_id=str(raw["session_id"]),
        active_minutes=float(raw["active_minutes"]),
        events_in_session=int(raw["events_in_session"]),
        last_verbs=tuple(str(v) for v in raw.get("last_verbs") or ()),
        current_course_id=str(raw["current_course_id"]) if raw.get("current_course_id") else None,
        struggle_score=float(raw["struggle_score"]),
        updated_at=datetime.fromisoformat(str(raw["updated_at"])),
        started_at=datetime.fromisoformat(str(raw["started_at"]))
        if raw.get("started_at")
        else None,
    )
