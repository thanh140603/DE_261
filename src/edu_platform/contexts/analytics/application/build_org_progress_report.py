"""Use case BR6: skill progress and completion per organisation with k-anonymity."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from edu_platform.contexts.analytics.domain.model import MinCohortPolicy, OrgProgressReport
from edu_platform.contexts.telemetry.domain.events import LearningEvent, Verb
from edu_platform.shared_kernel.domain.ids import CourseId, OrganisationId


@dataclass(frozen=True)
class EnrollmentFact:
    learner_pseudonym: str
    organisation_id: str
    course_id: str


@dataclass(frozen=True)
class CourseFact:
    course_id: str
    skill: str
    lesson_content_ids: tuple[str, ...]


class BuildOrgProgressReport:
    def __init__(self, policy: MinCohortPolicy) -> None:
        self._policy = policy

    def execute(
        self,
        organisation_id: str,
        enrollments: list[EnrollmentFact],
        courses: list[CourseFact],
        events: list[LearningEvent],
        mastery: dict[str, float],  # learner_pseudonym -> avg pass rate
        as_of: date,
    ) -> list[OrgProgressReport]:
        completed: dict[tuple[str, str], set[str]] = defaultdict(set)
        for e in events:
            if e.verb is Verb.COMPLETED and e.content_id:
                completed[(e.learner_pseudonym, e.course_id)].add(e.content_id)
        by_course: dict[str, list[EnrollmentFact]] = defaultdict(list)
        for en in enrollments:
            if en.organisation_id == organisation_id:
                by_course[en.course_id].append(en)
        out: list[OrgProgressReport] = []
        for course in courses:
            cohort = by_course.get(course.course_id, [])
            size = len(cohort)
            if size < self._policy.k:
                out.append(
                    OrgProgressReport(
                        OrganisationId(organisation_id),
                        CourseId(course.course_id),
                        course.skill,
                        size,
                        None,
                        None,
                        as_of,
                    )
                )
                continue
            lessons = set(course.lesson_content_ids) or {"_"}
            rates = [
                len(completed[(en.learner_pseudonym, course.course_id)] & lessons) / len(lessons)
                for en in cohort
            ]
            masteries = [mastery.get(en.learner_pseudonym, 0.0) for en in cohort]
            out.append(
                OrgProgressReport(
                    OrganisationId(organisation_id),
                    CourseId(course.course_id),
                    course.skill,
                    size,
                    round(sum(rates) / size, 3),
                    round(sum(masteries) / size, 3),
                    as_of,
                )
            )
        return out
