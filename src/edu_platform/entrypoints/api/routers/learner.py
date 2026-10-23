from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from edu_platform.contexts.recommendation.domain.next_step_policy import CourseRef, LessonRef
from edu_platform.contexts.telemetry.domain.events import Verb
from edu_platform.demo import seed
from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.serializers import notification_dict, submission_dict
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


@router.get("/learners/{learner_id}/recommendations")
async def recommendations(learner_id: str, p: DemoPlatform = Depends(platform)) -> dict[str, Any]:
    learner = _learner(learner_id)
    pseudonym = p.pseudonym(learner_id)
    completed_events = [
        event
        for event in p.silver.all()
        if event.learner_pseudonym == pseudonym
        and event.verb is Verb.COMPLETED
        and event.content_id is not None
    ]
    completed_content_ids = {str(event.content_id) for event in completed_events}
    lessons = [
        LessonRef(c.id, it.id, it.title, it.ordinal, it.content_id)
        for c in seed.COURSES
        if c.id in learner.course_ids
        for it in c.lessons
    ]
    next_step = p.next_step.next_step(lessons, completed_content_ids, list(learner.course_ids))
    last_skill: str | None = None
    if completed_events:
        latest = max(completed_events, key=lambda event: event.occurred_at)
        found = seed.lesson_by_content(str(latest.content_id))
        if found is not None:
            last_skill = found[0].skill
    courses = p.next_step.suggest_courses(
        [CourseRef(c.id, c.title, c.skill) for c in seed.COURSES],
        list(learner.course_ids),
        last_skill,
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
        "features": {"longterm": None, "session": None},
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
