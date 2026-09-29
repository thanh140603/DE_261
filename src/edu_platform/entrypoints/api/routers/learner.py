from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from edu_platform.contexts.recommendation.application.compute_batch_features import (
    ComputeBatchFeaturesCommand,
    GradedFact,
)
from edu_platform.contexts.recommendation.domain.next_step_policy import CourseRef, LessonRef
from edu_platform.contexts.telemetry.domain.events import Verb
from edu_platform.demo import seed
from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.serializers import (
    longterm_dict,
    notification_dict,
    session_dict,
    submission_dict,
)
from edu_platform.demo.simulator import Simulator
from edu_platform.entrypoints.api.deps import platform, simulator
from edu_platform.shared_kernel.domain.ids import LearnerId, SubmissionId

router = APIRouter(tags=["learner"])


def _learner(learner_id: str) -> seed.Learner:
    try:
        return seed.learner(learner_id)
    except StopIteration as exc:
        raise HTTPException(404, f"unknown learner {learner_id}") from exc


@router.get("/learners/{learner_id}/notifications")
async def notifications(
    learner_id: str, p: DemoPlatform = Depends(platform)
) -> list[dict[str, Any]]:
    _learner(learner_id)
    return [notification_dict(n) for n in p.notifications.for_recipient(learner_id)]


def refresh_batch_features(p: DemoPlatform) -> None:
    """Runs the batch branch on demand (the Spark job does this daily)."""
    pseudonyms = {it.id: p.pseudonym(it.id) for it in seed.LEARNERS}
    graded = [
        GradedFact(
            pseudonyms[s.learner_id],
            seed.assignment(s.assignment_id).course_id,
            s.result.pass_rate,
            s.submitted_at,
        )
        for s in p.submissions.all()
        if s.result is not None and s.learner_id in pseudonyms
    ]
    p.batch_features.execute(
        ComputeBatchFeaturesCommand(
            as_of=datetime.now(tz=UTC),
            events=p.silver.all(),
            graded=graded,
            lessons_per_course={c.id: len(c.lessons) for c in seed.COURSES},
            course_skill={c.id: c.skill for c in seed.COURSES},
        )
    )


@router.get("/learners/{learner_id}/recommendations")
async def recommendations(learner_id: str, p: DemoPlatform = Depends(platform)) -> dict[str, Any]:
    learner = _learner(learner_id)
    pseudonym = p.pseudonym(learner_id)
    refresh_batch_features(p)
    longterm = p.online_features.get_longterm(pseudonym)
    session = p.online_features.get_session(pseudonym)
    completed = {
        e.content_id
        for e in p.silver.all()
        if e.learner_pseudonym == pseudonym and e.verb is Verb.COMPLETED and e.content_id
    }
    lessons = [
        LessonRef(c.id, it.id, it.title, it.ordinal)
        for c in seed.COURSES
        if c.id in learner.course_ids
        for it in c.lessons
    ]
    completed_lessons = {
        it.lesson_id
        for it in lessons
        if seed.course(it.course_id).lessons[it.ordinal - 1].content_id in completed
    }
    next_step = p.next_step.next_step(lessons, completed_lessons, session, list(learner.course_ids))
    courses = p.next_step.suggest_courses(
        [CourseRef(c.id, c.title, c.skill) for c in seed.COURSES],
        list(learner.course_ids),
        longterm,
    )
    return {
        "next_step": (
            {
                "course_id": next_step.course_id,
                "lesson_id": next_step.lesson_id,
                "title": next_step.title,
                "reason": next_step.reason,
            }
            if next_step
            else None
        ),
        "courses": [
            {"course_id": r.course_id, "title": r.title, "score": r.score, "reason": r.reason}
            for r in courses
        ],
        "features": {"longterm": longterm_dict(longterm), "session": session_dict(session)},
    }


class SubmissionBody(BaseModel):
    learner_id: str
    assignment_id: str
    code: str


@router.post("/submissions", status_code=202)
async def submit(body: SubmissionBody, sim: Simulator = Depends(simulator)) -> dict[str, Any]:
    _learner(body.learner_id)
    try:
        seed.assignment(body.assignment_id)
    except StopIteration as exc:
        raise HTTPException(404, f"unknown assignment {body.assignment_id}") from exc
    import asyncio

    submission = await asyncio.to_thread(sim.submit, body.learner_id, body.assignment_id, body.code)
    sim.p.broadcaster.publish("stats", sim.stats())
    return {"submission_id": submission.id, "status": "queued"}


@router.get("/submissions/{submission_id}")
async def submission(submission_id: str, p: DemoPlatform = Depends(platform)) -> dict[str, Any]:
    s = p.submissions.get(SubmissionId(submission_id))
    if s is None:
        raise HTTPException(404, f"unknown submission {submission_id}")
    return submission_dict(s)


@router.get("/learners/{learner_id}/submissions")
async def learner_submissions(
    learner_id: str, p: DemoPlatform = Depends(platform)
) -> list[dict[str, Any]]:
    _learner(learner_id)
    rows = sorted(
        p.submissions.for_learner(LearnerId(learner_id)), key=lambda s: s.submitted_at, reverse=True
    )
    return [submission_dict(s, include_stdout=False) for s in rows]
