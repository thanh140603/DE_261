from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from edu_platform.br45 import classroom as study
from edu_platform.contexts.recommendation.domain.next_step_policy import CourseRef, FeatureContext
from edu_platform.demo import seed
from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.serializers import (
    longterm_dict,
    notification_dict,
    session_dict,
    submission_dict,
)
from edu_platform.demo.simulator import Simulator
from edu_platform.entrypoints.api.deps import (
    enrollment_repo,
    notification_repo,
    platform,
    settings,
    simulator,
)
from edu_platform.entrypoints.api.grading_client import (
    GradingNotFound,
    GradingServiceError,
    GradingUnavailable,
)
from edu_platform.platform.config import Settings
from edu_platform.shared_kernel.domain.ids import LearnerId, SubmissionId

from .classroom import enabled, owner

router = APIRouter(tags=["learner"])


def _learner(learner_id: str) -> seed.Learner:
    try:
        return seed.learner(learner_id)
    except StopIteration as exc:
        raise HTTPException(404, f"unknown learner {learner_id}") from exc


def _check_learner(request: Request, learner_id: str) -> None:
    if enabled(request):
        owner(request, learner_id)
    _learner(learner_id)


@router.get("/learners/{learner_id}/notifications")
async def notifications(
    learner_id: str,
    request: Request,
    p: DemoPlatform = Depends(platform),
    repo: Any = Depends(notification_repo),
) -> list[dict[str, Any]]:
    _check_learner(request, learner_id)
    rows = (
        repo.for_recipient(learner_id)
        if repo is not None
        else p.notifications.for_recipient(learner_id)
    )
    return [notification_dict(n) for n in rows]


@router.get("/learners/{learner_id}/recommendations")
async def recommendations(
    learner_id: str,
    request: Request,
    p: DemoPlatform = Depends(platform),
) -> dict[str, Any]:
    _check_learner(request, learner_id)
    enrolled_ids = p.enrollments[learner_id]
    completed_ids = p.completed_courses[learner_id]
    catalogue = [CourseRef(c.id, c.title, c.difficulty, c.category) for c in seed.COURSES]
    learner_features = p.load_features.execute(p.pseudonym(learner_id))
    context = FeatureContext(longterm=learner_features.longterm, session=learner_features.session)
    next_step = p.next_step.next_course_to_enroll(catalogue, enrolled_ids, completed_ids, context)
    suggested = p.next_step.suggest_courses(catalogue, enrolled_ids, completed_ids, context)

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
        "features": {
            "longterm": longterm_dict(learner_features.longterm),
            "session": session_dict(learner_features.session),
        },
    }


class CourseActionBody(BaseModel):
    course_id: str


@router.post("/learners/{learner_id}/enroll")
async def enroll(
    learner_id: str,
    body: CourseActionBody,
    request: Request,
    p: DemoPlatform = Depends(platform),
    repo: Any = Depends(enrollment_repo),
) -> dict[str, Any]:
    _check_learner(request, learner_id)
    learner = _learner(learner_id)
    try:
        seed.course(body.course_id)
    except StopIteration as exc:
        raise HTTPException(404, f"unknown course {body.course_id}") from exc
    if enabled(request):
        await asyncio.to_thread(study.change_enrollment, learner_id, body.course_id, False)
    if repo is not None:
        try:
            repo.enroll(learner_id, body.course_id, learner.org_id)
        except Exception as exc:
            raise HTTPException(503, f"could not persist enrollment: {exc}") from exc
    p.enroll(learner_id, body.course_id)
    return {"enrolled": p.enrollments[learner_id]}


@router.post("/learners/{learner_id}/complete-course")
async def complete_course(
    learner_id: str,
    body: CourseActionBody,
    request: Request,
    p: DemoPlatform = Depends(platform),
    repo: Any = Depends(enrollment_repo),
) -> dict[str, Any]:
    _check_learner(request, learner_id)
    try:
        seed.course(body.course_id)
    except StopIteration as exc:
        raise HTTPException(404, f"unknown course {body.course_id}") from exc
    if enabled(request):
        await asyncio.to_thread(study.change_enrollment, learner_id, body.course_id, True)
    if repo is not None:
        try:
            repo.complete(learner_id, body.course_id)
        except Exception as exc:
            raise HTTPException(503, f"could not persist completion: {exc}") from exc
    p.complete_course(learner_id, body.course_id)
    return {"completed": sorted(p.completed_courses[learner_id])}


class SubmissionBody(BaseModel):
    learner_id: str
    assignment_id: str
    code: str
    request_id: UUID | None = None


@router.post("/submissions", status_code=202)
async def submit(
    body: SubmissionBody,
    request: Request,
    sim: Simulator = Depends(simulator),
    cfg: Settings = Depends(settings),
) -> dict[str, Any]:
    if enabled(request):
        student = owner(request, body.learner_id)
        if body.request_id is None or not 1 <= len(body.code) <= 65536:
            raise HTTPException(422, "Supply a request ID and between 1 and 65536 code characters")
        submission_id = await asyncio.to_thread(
            study.submit,
            sim,
            student,
            body.assignment_id,
            body.code,
            str(body.request_id),
        )
        sim.p.broadcaster.publish("stats", sim.stats())
        return {"submission_id": submission_id, "status": "queued"}
    _learner(body.learner_id)
    try:
        seed.assignment(body.assignment_id)
    except StopIteration as exc:
        raise HTTPException(404, f"unknown assignment {body.assignment_id}") from exc
    if cfg.br13_mode == "service":
        client = request.app.state.grading
        if client is None:
            raise HTTPException(503, "grading service is not configured")
        try:
            return await asyncio.to_thread(
                client.submit, body.learner_id, body.assignment_id, body.code
            )
        except GradingNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except GradingUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except GradingServiceError as exc:
            raise HTTPException(422, str(exc)) from exc
    submission = await asyncio.to_thread(sim.submit, body.learner_id, body.assignment_id, body.code)
    sim.p.broadcaster.publish("stats", sim.stats())
    return {"submission_id": submission.id, "status": "queued"}


@router.get("/submissions/{submission_id}")
async def submission(
    submission_id: str,
    request: Request,
    p: DemoPlatform = Depends(platform),
    cfg: Settings = Depends(settings),
) -> dict[str, Any]:
    if enabled(request):
        result = await asyncio.to_thread(study.feedback, owner(request), submission_id)
        if not result:
            raise HTTPException(404, "Submission not found")
        return result[0]
    if cfg.br13_mode == "service":
        client = request.app.state.grading
        if client is None:
            raise HTTPException(503, "grading service is not configured")
        try:
            return await asyncio.to_thread(client.submission, submission_id)
        except GradingNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except GradingUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
    s = p.submissions.get(SubmissionId(submission_id))
    if s is None:
        raise HTTPException(404, f"unknown submission {submission_id}")
    return submission_dict(s)


@router.get("/learners/{learner_id}/submissions")
async def learner_submissions(
    learner_id: str,
    request: Request,
    p: DemoPlatform = Depends(platform),
    cfg: Settings = Depends(settings),
) -> list[dict[str, Any]]:
    _check_learner(request, learner_id)
    if enabled(request):
        return await asyncio.to_thread(study.feedback, learner_id)
    if cfg.br13_mode == "service":
        client = request.app.state.grading
        if client is None:
            raise HTTPException(503, "grading service is not configured")
        try:
            return await asyncio.to_thread(client.learner_submissions, learner_id)
        except GradingUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
    rows = sorted(
        p.submissions.for_learner(LearnerId(learner_id)),
        key=lambda s: s.submitted_at,
        reverse=True,
    )
    return [submission_dict(s, include_stdout=False) for s in rows]
