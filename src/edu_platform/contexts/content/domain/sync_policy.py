"""Domain policy (BR8): whether a captured content change must be (re)synchronised.

CDC delivers changes at least once and a backfill may replay old snapshots, so the sync
service decides against what the search index already holds, never against arrival order:
- a removal always applies (deletes are idempotent);
- a version newer than the indexed one applies;
- the indexed version itself applies only when forced (full reindex, chunking change);
- an older version is stale and is ignored, so a replay can never roll search back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from edu_platform.shared_kernel.domain import InvariantViolation, ValueObject
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId

from .model import ContentType


class SyncAction(StrEnum):
    APPLY = "apply"
    REMOVE = "remove"
    SKIP_DUPLICATE = "skip_duplicate"
    SKIP_STALE = "skip_stale"


@dataclass(frozen=True)
class ContentChange(ValueObject):
    """One row image of the LMS ``course_content`` table (current version of a document)."""

    content_id: ContentId
    course_id: CourseId
    content_type: ContentType
    title: str
    version: int
    object_key: str
    changed_at: datetime  # when the LMS published this version (row updated_at)
    deleted: bool = False
    object_version_id: str | None = None  # S3 version id when the key is overwritten in place

    def __post_init__(self) -> None:
        if self.version < 1:
            raise InvariantViolation("content version starts at 1")
        if not self.object_key:
            raise InvariantViolation("content change without an object key")


def decide(
    change: ContentChange, indexed_version: int | None, *, force: bool = False
) -> SyncAction:
    if change.deleted:
        return SyncAction.REMOVE
    if indexed_version is None or change.version > indexed_version:
        return SyncAction.APPLY
    if change.version == indexed_version:
        return SyncAction.APPLY if force else SyncAction.SKIP_DUPLICATE
    return SyncAction.SKIP_STALE
