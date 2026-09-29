"""Use case (Flink keyed state, or in-process): update SessionFeatures per event (BR2).

Session = events from one learner with gaps < 30 min. struggle_score rises with
rewinds (seeked) and repeated attempts and decays as the session goes on.
"""

from __future__ import annotations

from datetime import timedelta

from edu_platform.contexts.recommendation.application.ports import OnlineFeatureStore
from edu_platform.contexts.recommendation.domain.model import SessionFeatures
from edu_platform.contexts.telemetry.domain.events import LearningEvent

SESSION_GAP = timedelta(minutes=30)
STRUGGLE_VERBS = {"seeked": 1.0, "attempted": 0.6, "paused": 0.2}


class ComputeSessionFeatures:
    def __init__(self, online: OnlineFeatureStore) -> None:
        self._online = online
        self._started: dict[str, tuple[str, float]] = {}  # pseudonym -> (session_id, start_ts)

    def execute(self, event: LearningEvent) -> SessionFeatures:
        prev = self._online.get_session(event.learner_pseudonym)
        ts = event.occurred_at.timestamp()
        new_session = (
            prev is None
            or event.session_id != prev.session_id
            or event.occurred_at - prev.updated_at > SESSION_GAP
        )
        if new_session:
            self._started[event.learner_pseudonym] = (event.session_id, ts)
            prev = None
        start = self._started.get(event.learner_pseudonym, (event.session_id, ts))[1]
        verbs = ((prev.last_verbs if prev else ()) + (event.verb.value,))[-8:]
        n = (prev.events_in_session if prev else 0) + 1
        raw = sum(STRUGGLE_VERBS.get(v, 0.0) for v in verbs)
        struggle = round(min(1.0, raw / max(4.0, len(verbs))), 2)
        features = SessionFeatures(
            learner_pseudonym=event.learner_pseudonym,
            session_id=event.session_id,
            active_minutes=round(max(0.0, ts - start) / 60, 1),
            events_in_session=n,
            last_verbs=verbs,
            current_course_id=event.course_id,
            struggle_score=struggle,
            updated_at=event.occurred_at,
        )
        self._online.put_session(features)
        return features
