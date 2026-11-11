"""Session-feature use case (BR2 streaming branch).

A session is a learner's events with no inactivity gap longer than 30 minutes.
The streaming job groups events per learner (Spark ``session_window``); this
module is the pure, engine-independent policy used by that job and by tests.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from edu_platform.contexts.recommendation.domain.model import SessionFeatures
from edu_platform.contexts.telemetry.domain.events import LearningEvent

SESSION_GAP = timedelta(minutes=30)
STRUGGLE_VERBS = {"seeked": 1.0, "attempted": 0.6, "paused": 0.2}
LAST_VERBS = 8


@dataclass(frozen=True)
class SessionFeaturePolicy:
    gap: timedelta = SESSION_GAP

    def split(self, events: list[LearningEvent]) -> list[list[LearningEvent]]:
        """Split one learner's events into sessions, ordered by event time."""
        ordered = sorted(events, key=lambda event: event.occurred_at)
        sessions: list[list[LearningEvent]] = []
        for event in ordered:
            if not sessions or event.occurred_at - sessions[-1][-1].occurred_at > self.gap:
                sessions.append([event])
            else:
                sessions[-1].append(event)
        return sessions

    def compute(self, events: list[LearningEvent]) -> SessionFeatures | None:
        sessions = self.split(events)
        if not sessions:
            return None
        return self._features(sessions[-1])

    def compute_all(self, events: list[LearningEvent]) -> list[SessionFeatures]:
        return [self._features(session) for session in self.split(events)]

    def advance(self, previous: SessionFeatures | None, event: LearningEvent) -> SessionFeatures:
        """Incrementally add one event to the learner's live session.

        Used by the streaming job's Redis-backed state. A session id change or a gap
        longer than ``gap`` starts a new session; otherwise the counters advance.
        """
        if previous is None:
            return self._features([event])
        gap = event.occurred_at - previous.updated_at
        if event.session_id != previous.session_id or gap > self.gap:
            return self._features([event])
        started = previous.started_at or (
            previous.updated_at - timedelta(minutes=previous.active_minutes)
        )
        verbs = (*previous.last_verbs, event.verb.value)[-LAST_VERBS:]
        raw = sum(STRUGGLE_VERBS.get(verb, 0.0) for verb in verbs)
        struggle = round(min(1.0, raw / max(4.0, len(verbs))), 2)
        updated = max(previous.updated_at, event.occurred_at)
        return SessionFeatures(
            learner_pseudonym=previous.learner_pseudonym,
            session_id=previous.session_id,
            active_minutes=round(max(0.0, (updated - started).total_seconds()) / 60, 1),
            events_in_session=previous.events_in_session + 1,
            last_verbs=verbs,
            current_course_id=event.course_id,
            struggle_score=struggle,
            updated_at=updated,
            started_at=started,
        )

    def _features(self, session: list[LearningEvent]) -> SessionFeatures:
        first, last = session[0], session[-1]
        verbs = tuple(event.verb.value for event in session)[-LAST_VERBS:]
        raw = sum(STRUGGLE_VERBS.get(verb, 0.0) for verb in verbs)
        struggle = round(min(1.0, raw / max(4.0, len(verbs))), 2)
        return SessionFeatures(
            learner_pseudonym=last.learner_pseudonym,
            session_id=last.session_id
            or f"{last.learner_pseudonym}:{first.occurred_at.isoformat()}",
            active_minutes=round(
                max(0.0, (last.occurred_at - first.occurred_at).total_seconds()) / 60, 1
            ),
            events_in_session=len(session),
            last_verbs=verbs,
            current_course_id=last.course_id,
            struggle_score=struggle,
            updated_at=last.occurred_at,
            started_at=first.occurred_at,
        )


def sessions_by_learner(
    events: list[LearningEvent], gap: timedelta = SESSION_GAP
) -> dict[str, list[list[LearningEvent]]]:
    """Group heterogeneous events by pseudonym, then split each stream into sessions."""
    by_learner: dict[str, list[LearningEvent]] = defaultdict(list)
    for event in events:
        by_learner[event.learner_pseudonym].append(event)
    policy = SessionFeaturePolicy(gap)
    return {pseudonym: policy.split(rows) for pseudonym, rows in by_learner.items()}
