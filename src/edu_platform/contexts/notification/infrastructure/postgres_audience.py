"""PostgreSQL-backed audience resolver (BR1), with a seed fallback.

The notification context is the one allowed to resolve real identities
(ADR 0007). It reads enrollments and advisor assignments from the LMS
Postgres, cached for 60 s, and falls back to the demo seed when the database
is unavailable (e.g. a local demo without the OLTP seed).
"""

from __future__ import annotations

import time
from typing import Any

from edu_platform.contexts.notification.infrastructure.in_memory import StaticAudienceResolver
from edu_platform.demo import seed


def _seed_resolver() -> StaticAudienceResolver:
    return StaticAudienceResolver(
        {c.id: [it.id for it in seed.LEARNERS if c.id in it.course_ids] for c in seed.COURSES},
        {it.id: it.advisor_id for it in seed.LEARNERS},
    )


class PostgresAudienceResolver:
    def __init__(self, postgres_dsn: str, cache_seconds: int = 60) -> None:
        self._dsn = postgres_dsn
        self._cache_seconds = cache_seconds
        self._fallback = _seed_resolver()
        self._cache: dict[str, Any] | None = None
        self._cached_at = 0.0

    def _load(self) -> dict[str, Any]:
        if self._cache is not None and (time.monotonic() - self._cached_at) < self._cache_seconds:
            return self._cache
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            learners = {
                course_id: [row[0] for row in rows]
                for course_id, rows in _group_by_course(
                    conn.execute(
                        "SELECT learner_id, course_id FROM enrollments "
                        "WHERE status IN ('active', 'completed') ORDER BY course_id"
                    ).fetchall()
                ).items()
            }
            advisors = {
                row[0]: row[1]
                for row in conn.execute("SELECT learner_id, advisor_id FROM learners").fetchall()
                if row[1] is not None
            }
        self._cache = {"learners": learners, "advisors": advisors}
        self._cached_at = time.monotonic()
        return self._cache

    def learners_for_course(self, course_id: str) -> list[str]:
        try:
            return list(self._load()["learners"].get(course_id, []))
        except Exception:
            return self._fallback.learners_for_course(course_id)

    def advisor_for_learner(self, learner_id: str) -> str | None:
        try:
            advisor = self._load()["advisors"].get(learner_id)
            return advisor if isinstance(advisor, str) else None
        except Exception:
            return self._fallback.advisor_for_learner(learner_id)


def _group_by_course(rows: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    grouped: dict[str, list[tuple[str, str]]] = {}
    for learner_id, course_id in rows:
        grouped.setdefault(course_id, []).append((learner_id, course_id))
    return grouped
