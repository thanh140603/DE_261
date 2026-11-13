from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from edu_platform.br45.auth import Advisor
from edu_platform.demo import seed
from edu_platform.demo.container import DemoPlatform
from edu_platform.entrypoints.api.deps import platform

router = APIRouter(prefix="/advisor", tags=["advisor"])


@router.get("/demo-alerts", deprecated=True)
async def alerts(user: Advisor, p: DemoPlatform = Depends(platform)) -> list[dict[str, Any]]:
    return [row for row in reversed(p.risk_alerts) if row["course_id"] in user.courses]


@router.get("/learners/{learner_id}/risk")
async def learner_risk(
    learner_id: str, user: Advisor, p: DemoPlatform = Depends(platform)
) -> dict[str, Any]:
    try:
        learner = seed.learner(learner_id)
    except StopIteration as exc:
        raise HTTPException(404, f"unknown learner {learner_id}") from exc
    courses = []
    for course_id in learner.course_ids:
        if course_id not in user.courses:
            continue
        profile = p.risk_repo.get(f"{learner_id}:{course_id}")
        courses.append(
            {
                "course_id": course_id,
                "course_title": seed.course(course_id).title,
                "score": profile.score.value if profile and profile.score else 0.0,
                "computed_at": profile.score.computed_at.isoformat()
                if profile and profile.score
                else None,
                "signals": [
                    {
                        "kind": s.kind.value,
                        "weight": s.weight,
                        "observed_at": s.observed_at.isoformat(),
                    }
                    for s in (profile.signals if profile else [])
                ],
                "history": [
                    {"at": h.computed_at.isoformat(), "score": h.value}
                    for h in (profile.history if profile else [])
                ],
                "last_alert_at": profile.last_alert_at.isoformat()
                if profile and profile.last_alert_at
                else None,
            }
        )
    if not courses:
        raise HTTPException(403, "Learner is outside your authorized courses")
    policy = p.risk_policy
    return {
        "learner_id": learner_id,
        "learner_name": learner.name,
        "courses": courses,
        "policy": {
            "window_days": policy.window_size.days,
            "slide_days": policy.slide.days,
            "alert_threshold": policy.alert_threshold,
            "cooldown_days": round(policy.cooldown.total_seconds() / 86400, 3),
        },
    }
