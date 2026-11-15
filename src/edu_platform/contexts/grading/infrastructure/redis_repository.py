"""Redis-backed grading adapters (BR3).

The submission aggregate is stored as JSON keyed by id. Each learner has a
sorted set scored by ``submitted_at`` (microseconds) so the newest page is
O(log n); the global set still backs ``all()`` for the demo analytics. The
attempt counter is a plain ``INCR`` per (learner, assignment), so accepting a
submission no longer scans the learner's history. A short TTL keeps the hot
store bounded; the lakehouse is the durable history (silver.submissions,
gold.fct_submission).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from edu_platform.contexts.grading.domain.model import Submission
from edu_platform.contexts.grading.infrastructure.serialization import (
    submission_from_dict,
    submission_to_dict,
)
from edu_platform.platform.storage.redis_client import key
from edu_platform.shared_kernel.domain.ids import LearnerId, SubmissionId

_SUBMISSION_TTL_SECONDS = 7 * 24 * 3600
_CODE_TTL_SECONDS = 3600


def _score(submitted_at: datetime) -> int:
    return int(submitted_at.timestamp() * 1_000_000)


def _timeline_key(learner_id: LearnerId) -> str:
    return key("grading", "timeline", learner_id)


def _attempts_key(learner_id: LearnerId, assignment_id: str) -> str:
    return key("grading", "attempts", learner_id, assignment_id)


class RedisSubmissionRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _get_many(self, ids: list[str]) -> list[Submission]:
        if not ids:
            return []
        keys = [key("grading", "submission", submission_id) for submission_id in ids]
        raws = self._client.mget(keys)
        return [submission_from_dict(json.loads(raw)) for raw in raws if raw is not None]

    def _index_timeline(self, learner_id: LearnerId, rows: list[Submission]) -> None:
        if not rows:
            return
        timeline = _timeline_key(learner_id)
        self._client.zadd(timeline, {s.id: _score(s.submitted_at) for s in rows})
        cutoff = _score(datetime.now(tz=UTC)) - _SUBMISSION_TTL_SECONDS * 1_000_000
        self._client.zremrangebyscore(timeline, 0, cutoff)
        self._client.expire(timeline, _SUBMISSION_TTL_SECONDS)

    def _backfill_timeline(self, learner_id: LearnerId) -> None:
        """Index submissions written before the timeline existed (legacy set).

        The legacy set is dropped after the backfill: ids of expired submissions
        stay in it forever, so keeping it would trigger a full reload on every
        read.
        """
        legacy_key = key("grading", "learner", learner_id)
        legacy = self._client.smembers(legacy_key)
        if legacy and self._client.zcard(_timeline_key(learner_id)) < len(legacy):
            self._index_timeline(learner_id, self._get_many(sorted(str(i) for i in legacy)))
            self._client.delete(legacy_key)

    def _get(self, submission_id: SubmissionId) -> Submission | None:
        raw = self._client.get(key("grading", "submission", submission_id))
        if raw is None:
            return None
        return submission_from_dict(json.loads(raw))

    def get(self, submission_id: SubmissionId) -> Submission | None:
        return self._get(submission_id)

    def save(self, submission: Submission) -> None:
        item_key = key("grading", "submission", submission.id)
        self._client.set(
            item_key, json.dumps(submission_to_dict(submission)), ex=_SUBMISSION_TTL_SECONDS
        )
        self._index_timeline(submission.learner_id, [submission])
        self._client.sadd(key("grading", "submissions"), submission.id)

    def for_learner(self, learner_id: LearnerId, limit: int | None = None) -> list[Submission]:
        """Newest-first submissions; ``limit`` reads only the newest page."""
        if limit is not None and limit <= 0:
            return []
        self._backfill_timeline(learner_id)
        stop = -1 if limit is None else limit - 1
        ids = self._client.zrevrange(_timeline_key(learner_id), 0, stop)
        return self._get_many([str(i) for i in ids])

    def next_attempt(self, learner_id: LearnerId, assignment_id: str) -> int:
        """O(1) attempt sequence per (learner, assignment).

        The counter is seeded once from the hot history so an existing learner
        keeps its numbering after a deploy; afterwards only ``INCR`` runs on the
        submission path.
        """
        counter = _attempts_key(learner_id, assignment_id)
        if not self._client.exists(counter):
            highest = max(
                (
                    s.attempt_number
                    for s in self.for_learner(learner_id)
                    if s.assignment_id == assignment_id
                ),
                default=0,
            )
            self._client.set(counter, highest, nx=True)
        return int(self._client.incr(counter))

    def all(self) -> list[Submission]:
        ids = self._client.smembers(key("grading", "submissions"))
        return self._get_many([str(i) for i in ids])


class RedisCodeStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    def put(self, submission_id: SubmissionId, code: str) -> str:
        ref = key("grading", "code", submission_id)
        self._client.set(ref, code, ex=_CODE_TTL_SECONDS)
        return ref

    def get(self, code_ref: str) -> str:
        value = self._client.get(code_ref)
        if value is None:
            raise KeyError(f"code not found: {code_ref}")
        return str(value)
