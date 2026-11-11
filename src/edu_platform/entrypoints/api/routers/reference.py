from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from edu_platform.demo import seed
from edu_platform.entrypoints.api.deps import settings
from edu_platform.platform.config import Settings

router = APIRouter(tags=["reference"])


@router.get("/health")
async def health(cfg: Settings = Depends(settings)) -> dict[str, str]:
    return {"status": "ok", "mode": cfg.br13_mode}


@router.get("/demo/overview")
async def overview() -> dict[str, Any]:
    return {
        "organisations": [{"id": o.id, "name": o.name} for o in seed.ORGANISATIONS],
        "courses": [
            {
                "id": c.id,
                "title": c.title,
                "org_id": c.org_id,
                "skill": c.skill,
                "lessons": [
                    {
                        "id": it.id,
                        "title": it.title,
                        "content_id": it.content_id,
                        "duration_sec": it.duration_sec,
                    }
                    for it in c.lessons
                ],
            }
            for c in seed.COURSES
        ],
        "learners": [
            {
                "id": it.id,
                "name": it.name,
                "org_id": it.org_id,
                "course_ids": list(it.course_ids),
                "advisor_id": it.advisor_id,
            }
            for it in seed.LEARNERS
        ],
        "assignments": [
            {
                "id": a.id,
                "title": a.title,
                "course_id": a.course_id,
                "language": a.language,
                "prompt": a.prompt,
                "starter_code": a.starter_code,
                "test_case_ids": [t.id for t in a.tests],
            }
            for a in seed.ASSIGNMENTS
        ],
        "advisors": [{"id": a.id, "name": a.name} for a in seed.ADVISORS],
    }
