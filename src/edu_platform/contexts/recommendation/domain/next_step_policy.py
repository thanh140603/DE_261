"""Domain service: rule-based next-step and next-course recommendation (BR2).

Pure by design: the policy only sees the course catalogue, the learner's
completed content ids and their enrolled courses. It has no session state, no
feature store and no model, so it can be unit-tested without any engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Recommendation


@dataclass(frozen=True)
class LessonRef:
    course_id: str
    lesson_id: str
    title: str
    ordinal: int
    content_id: str


@dataclass(frozen=True)
class CourseRef:
    course_id: str
    title: str
    skill: str


class NextStepPolicy:
    def next_step(
        self,
        lessons: list[LessonRef],
        completed_content_ids: set[str],
        enrolled_course_ids: list[str],
    ) -> Recommendation | None:
        """First unfinished lesson, by course enrollment order and lesson ordinal."""
        for course_id in enrolled_course_ids:
            pending = sorted(
                (
                    lesson
                    for lesson in lessons
                    if lesson.course_id == course_id
                    and lesson.content_id not in completed_content_ids
                ),
                key=lambda lesson: lesson.ordinal,
            )
            if pending:
                lesson = pending[0]
                return Recommendation(
                    course_id=lesson.course_id,
                    lesson_id=lesson.lesson_id,
                    title=lesson.title,
                    reason="Next unfinished lesson in this course.",
                    score=1.0,
                )
        return None

    def suggest_courses(
        self,
        catalogue: list[CourseRef],
        enrolled_course_ids: list[str],
        last_skill: str | None = None,
    ) -> list[Recommendation]:
        """Up to three unenrolled courses, same-skill continuation first."""
        enrolled = set(enrolled_course_ids)
        suggestions = [
            Recommendation(
                course_id=course.course_id,
                lesson_id=None,
                title=course.title,
                reason=(
                    f"Builds on your {course.skill} work."
                    if last_skill and course.skill == last_skill
                    else f"Explore {course.skill}."
                ),
                score=1.0 if last_skill and course.skill == last_skill else 0.5,
            )
            for course in catalogue
            if course.course_id not in enrolled
        ]
        suggestions.sort(key=lambda recommendation: (-recommendation.score, recommendation.title))
        return suggestions[:3]
