"""Redis-backed grading adapters (BR3).

The submission aggregate is stored as JSON keyed by id, with an id list per
learner and one global set so ``all()``/``for_learner()`` are index lookups
rather than scans. A short TTL keeps the hot store bounded; the lakehouse is
the durable history (silver.submissions, gold.fct_submission).
"""

from __future__ import annotations

import json
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


class RedisSubmissionRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

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
        self._client.sadd(key("grading", "learner", submission.learner_id), submission.id)
        self._client.sadd(key("grading", "submissions"), submission.id)

    def for_learner(self, learner_id: LearnerId) -> list[Submission]:
        ids = self._client.smembers(key("grading", "learner", learner_id))
        rows = [self._get(SubmissionId(str(i))) for i in ids]
        return sorted(
            (s for s in rows if s is not None), key=lambda s: s.submitted_at, reverse=True
        )

    def all(self) -> list[Submission]:
        ids = self._client.smembers(key("grading", "submissions"))
        return [s for s in (self._get(SubmissionId(str(i))) for i in ids) if s is not None]


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
