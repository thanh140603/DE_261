from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from edu_platform.contexts.analytics.application.build_org_progress_report import (
    CourseFact,
    EnrollmentFact,
)
from edu_platform.demo import seed
from edu_platform.demo.container import DemoPlatform
from edu_platform.entrypoints.api.deps import platform
from edu_platform.entrypoints.api.routers.learner import refresh_batch_features

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/organisations/{org_id}/progress")
async def progress(org_id: str, p: DemoPlatform = Depends(platform)) -> dict[str, Any]:
    if org_id not in {o.id for o in seed.ORGANISATIONS}:
        raise HTTPException(404, f"unknown organisation {org_id}")
    refresh_batch_features(p)
    enrollments = [
        EnrollmentFact(p.pseudonym(it.id), it.org_id, c)
        for it in seed.LEARNERS
        for c in it.course_ids
    ]
    courses = [
        CourseFact(c.id, c.skill, tuple(it.content_id for it in c.lessons)) for c in seed.COURSES
    ]
    mastery = {}
    for it in seed.LEARNERS:
        f = p.online_features.get_longterm(p.pseudonym(it.id))
        if f:
            mastery[p.pseudonym(it.id)] = f.avg_pass_rate_30d
    rows = p.org_report.execute(
        org_id, enrollments, courses, p.silver.all(), mastery, datetime.now(tz=UTC).date()
    )
    return {
        "organisation_id": org_id,
        "as_of": datetime.now(tz=UTC).date().isoformat(),
        "min_cohort": 5,
        "rows": [
            {
                "course_id": r.course_id,
                "course_title": seed.course(r.course_id).title,
                "skill": r.skill,
                "cohort_size": r.cohort_size,
                "completion_rate": r.completion_rate,
                "avg_mastery": r.avg_mastery,
                "suppressed": r.completion_rate is None,
            }
            for r in rows
        ],
    }
