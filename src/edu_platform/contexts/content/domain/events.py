from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from edu_platform.shared_kernel.domain import DomainEvent
from edu_platform.shared_kernel.domain.ids import CourseId


@dataclass(frozen=True, kw_only=True)
class ContentVersionPublished(DomainEvent):
    event_type: ClassVar[str] = "content.version_published.v1"
    course_id: CourseId
    version: int


@dataclass(frozen=True, kw_only=True)
class ContentIndexed(DomainEvent):
    event_type: ClassVar[str] = "content.indexed.v1"
    version: int
    chunk_count: int
