"""Use case (Spark daily, or in-process): long-term features from silver (BR2 batch branch).

Pure over already-loaded silver rows so the Spark job only has to collect per
learner partitions; the demo calls it directly on in-memory lists.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from edu_platform.contexts.recommendation.application.ports import OnlineFeatureStore
from edu_platform.contexts.recommendation.domain.model import LongTermFeatures
from edu_platform.contexts.telemetry.domain.events import LearningEvent, Verb


@dataclass(frozen=True)
class GradedFact:
    learner_pseudonym: str
    course_id: str
    pass_rate: float
    at: datetime


@dataclass(frozen=True)
class ComputeBatchFeaturesCommand:
    as_of: datetime
    events: list[LearningEvent]
    graded: list[GradedFact]
    lessons_per_course: dict[str, int]
    course_skill: dict[str, str]


class ComputeBatchFeatures:
    def __init__(self, online: OnlineFeatureStore) -> None:
        self._online = online

    def execute(self, command: ComputeBatchFeaturesCommand) -> list[LongTermFeatures]:
        since = command.as_of - timedelta(days=30)
        events = [e for e in command.events if e.occurred_at >= since]
        graded = [g for g in command.graded if g.at >= since]
        by_learner: dict[str, list[LearningEvent]] = defaultdict(list)
        for e in events:
            by_learner[e.learner_pseudonym].append(e)
        graded_by: dict[str, list[GradedFact]] = defaultdict(list)
        for g in graded:
            graded_by[g.learner_pseudonym].append(g)

        out: list[LongTermFeatures] = []
        for pseudonym, evs in by_learner.items():
            completed = {(e.course_id, e.content_id) for e in evs if e.verb is Verb.COMPLETED}
            courses = {e.course_id for e in evs}
            total_lessons = sum(command.lessons_per_course.get(c, 0) for c in courses) or 1
            mastery: dict[str, list[float]] = defaultdict(list)
            for g in graded_by.get(pseudonym, []):
                mastery[command.course_skill.get(g.course_id, "general")].append(g.pass_rate)
            for c, _ in completed:
                mastery[command.course_skill.get(c, "general")].append(1.0)
            grades = [g.pass_rate for g in graded_by.get(pseudonym, [])]
            out.append(
                LongTermFeatures(
                    learner_pseudonym=pseudonym,
                    completion_rate_30d=round(min(1.0, len(completed) / total_lessons), 3),
                    avg_pass_rate_30d=round(sum(grades) / len(grades), 3) if grades else 0.0,
                    active_days_30d=len({e.occurred_at.date() for e in evs}),
                    preferred_platform=Counter(e.platform.value for e in evs).most_common(1)[0][0],
                    skill_mastery={k: round(sum(v) / len(v), 2) for k, v in mastery.items()},
                    computed_at=command.as_of,
                )
            )
        for row in out:
            self._online.put_longterm(row)
        return out
