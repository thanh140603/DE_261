from __future__ import annotations

from edu_platform.contexts.recommendation.domain.next_step_policy import (
    CourseRef,
    LessonRef,
    NextStepPolicy,
)


def _lesson(course_id: str, ordinal: int, content_id: str | None = None) -> LessonRef:
    return LessonRef(
        course_id=course_id,
        lesson_id=f"{course_id}-l{ordinal}",
        title=f"Lesson {ordinal}",
        ordinal=ordinal,
        content_id=content_id or f"{course_id}-c{ordinal}",
    )


def test_next_step_returns_first_unfinished_lesson() -> None:
    policy = NextStepPolicy()
    lessons = [_lesson("c1", 1), _lesson("c1", 2), _lesson("c2", 1)]
    recommendation = policy.next_step(lessons, set(), ["c1", "c2"])
    assert recommendation is not None
    assert recommendation.lesson_id == "c1-l1"


def test_next_step_skips_completed_lessons() -> None:
    policy = NextStepPolicy()
    lessons = [_lesson("c1", 1), _lesson("c1", 2)]
    recommendation = policy.next_step(lessons, {"c1-c1"}, ["c1"])
    assert recommendation is not None
    assert recommendation.lesson_id == "c1-l2"


def test_next_step_is_none_when_everything_is_complete() -> None:
    policy = NextStepPolicy()
    lessons = [_lesson("c1", 1)]
    assert policy.next_step(lessons, {"c1-c1"}, ["c1"]) is None


def test_next_step_is_idempotent_for_duplicate_completed_events() -> None:
    policy = NextStepPolicy()
    lessons = [_lesson("c1", 1), _lesson("c1", 2)]
    completed = {"c1-c1"}  # duplicate completed events collapse to one id
    first = policy.next_step(lessons, completed, ["c1"])
    second = policy.next_step(lessons, completed, ["c1"])
    assert first == second
    assert first is not None and first.lesson_id == "c1-l2"


def test_suggest_courses_excludes_enrolled_and_ranks_same_skill_first() -> None:
    policy = NextStepPolicy()
    catalogue = [
        CourseRef("a", "Python A", "python"),
        CourseRef("b", "SQL B", "sql"),
        CourseRef("c", "Python C", "python"),
    ]
    suggestions = policy.suggest_courses(catalogue, ["a"], "python")
    assert [r.course_id for r in suggestions] == ["c", "b"]


def test_suggest_courses_caps_at_three() -> None:
    policy = NextStepPolicy()
    catalogue = [CourseRef(f"c{i}", f"Course {i}", "skill") for i in range(5)]
    assert len(policy.suggest_courses(catalogue, [])) == 3
