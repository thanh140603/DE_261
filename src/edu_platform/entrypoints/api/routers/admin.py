from __future__ import annotations

from collections import defaultdict
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

router = APIRouter(prefix="/admin", tags=["admin"])


def _mastery_by_pseudonym(p: DemoPlatform) -> dict[str, float]:
    """Mean graded pass rate per learner, keyed by pseudonym.

    Deliberately self-contained: BR6 must not depend on BR2's feature code,
    so mastery is read straight from graded submissions.
    """
    rates: dict[str, list[float]] = defaultdict(list)
    for submission in p.submissions.all():
        if submission.result is not None:
            rates[str(submission.learner_id)].append(submission.result.pass_rate)
    return {
        p.pseudonym(learner_id): round(sum(rs) / len(rs), 3) for learner_id, rs in rates.items()
    }


@router.get("/organisations/{org_id}/progress")
async def progress(org_id: str, p: DemoPlatform = Depends(platform)) -> dict[str, Any]:
    if org_id not in {o.id for o in seed.ORGANISATIONS}:
        raise HTTPException(404, f"unknown organisation {org_id}")
    enrollments = [
        EnrollmentFact(p.pseudonym(it.id), it.org_id, c)
        for it in seed.LEARNERS
        for c in it.course_ids
    ]
    courses = [
        CourseFact(c.id, c.skill, tuple(it.content_id for it in c.lessons)) for c in seed.COURSES
    ]
    rows = p.org_report.execute(
        org_id,
        enrollments,
        courses,
        p.silver.all(),
        _mastery_by_pseudonym(p),
        datetime.now(tz=UTC).date(),
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
