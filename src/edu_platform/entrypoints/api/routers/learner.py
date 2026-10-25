from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from edu_platform.contexts.recommendation.domain.next_step_policy import CourseRef
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
    _learner(learner_id)
    enrolled_ids = p.enrollments[learner_id]
    completed_ids = p.completed_courses[learner_id]
    catalogue = [CourseRef(c.id, c.title, c.difficulty, c.category) for c in seed.COURSES]
    next_step = p.next_step.next_course_to_enroll(catalogue, enrolled_ids, completed_ids)
    suggested = p.next_step.suggest_courses(catalogue, enrolled_ids, completed_ids)

    def course_dict(course_id: str) -> dict[str, str]:
        course = seed.course(course_id)
        return {
            "course_id": course.id,
            "title": course.title,
            "difficulty": course.difficulty,
            "category": course.category,
        }

    return {
        "next_step": (
            {
                **course_dict(next_step.course_id),
                "score": next_step.score,
                "reason": next_step.reason,
            }
            if next_step
            else None
        ),
        "enrolled": [
            {**course_dict(course_id), "completed": course_id in completed_ids}
            for course_id in enrolled_ids
        ],
        "courses": [
            {**course_dict(r.course_id), "score": r.score, "reason": r.reason} for r in suggested
        ],
    }


class CourseActionBody(BaseModel):
    course_id: str


@router.post("/learners/{learner_id}/enroll")
async def enroll(
    learner_id: str, body: CourseActionBody, p: DemoPlatform = Depends(platform)
) -> dict[str, Any]:
    _learner(learner_id)
    try:
        seed.course(body.course_id)
    except StopIteration as exc:
        raise HTTPException(404, f"unknown course {body.course_id}") from exc
    p.enroll(learner_id, body.course_id)
    return {"enrolled": p.enrollments[learner_id]}


@router.post("/learners/{learner_id}/complete-course")
async def complete_course(
    learner_id: str, body: CourseActionBody, p: DemoPlatform = Depends(platform)
) -> dict[str, Any]:
    _learner(learner_id)
    try:
        seed.course(body.course_id)
    except StopIteration as exc:
        raise HTTPException(404, f"unknown course {body.course_id}") from exc
    p.complete_course(learner_id, body.course_id)
    return {"completed": sorted(p.completed_courses[learner_id])}


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
