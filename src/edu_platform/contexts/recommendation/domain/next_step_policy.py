"""Domain service: turn features into a next step and course suggestions (BR2).

Rule-based v1 so the demo is explainable: every recommendation carries a
plain-language reason. Swap for a model behind the same interface later.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import LongTermFeatures, Recommendation, SessionFeatures


@dataclass(frozen=True)
class LessonRef:
    course_id: str
    lesson_id: str
    title: str
    ordinal: int


@dataclass(frozen=True)
class CourseRef:
    course_id: str
    title: str
    skill: str


class NextStepPolicy:
    def next_step(
        self,
        lessons: list[LessonRef],
        completed_lesson_ids: set[str],
        session: SessionFeatures | None,
        enrolled_course_ids: list[str],
    ) -> Recommendation | None:
        if not lessons:
            return None
        course_order = list(enrolled_course_ids)
        if session and session.current_course_id in course_order:
            course_order.remove(session.current_course_id)
            course_order.insert(0, session.current_course_id)
        for course_id in course_order:
            pending = sorted(
                (
                    it
                    for it in lessons
                    if it.course_id == course_id and it.lesson_id not in completed_lesson_ids
                ),
                key=lambda it: it.ordinal,
            )
            if not pending:
                continue
            lesson = pending[0]
            if session and session.struggle_score >= 0.5 and session.current_course_id == course_id:
                reason = (
                    "You rewound and retried a lot this session, "
                    "so revisit this lesson before moving on."
                )
            elif session and session.current_course_id == course_id:
                reason = "Next unfinished lesson in the course you are working on right now."
            else:
                reason = "First unfinished lesson in your enrolled courses."
            return Recommendation(course_id, lesson.lesson_id, lesson.title, reason, 1.0)
        return None

    def suggest_courses(
        self,
        catalogue: list[CourseRef],
        enrolled_course_ids: list[str],
        longterm: LongTermFeatures | None,
    ) -> list[Recommendation]:
        out: list[Recommendation] = []
        mastery = longterm.skill_mastery if longterm else {}
        for course in catalogue:
            if course.course_id in enrolled_course_ids:
                continue
            level = mastery.get(course.skill, 0.0)
            score = round(1.0 - level, 2)
            reason = (
                f"Your {course.skill} mastery is {level:.0%}; this course builds it."
                if longterm
                else "No history yet; popular starting point."
            )
            out.append(Recommendation(course.course_id, None, course.title, reason, score))
        return sorted(out, key=lambda r: -r.score)[:3]
