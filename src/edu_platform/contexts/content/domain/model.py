from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from edu_platform.shared_kernel.domain import AggregateRoot, Entity, InvariantViolation, ValueObject
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId

from .events import ContentIndexed, ContentVersionPublished


class ContentType(StrEnum):
    VIDEO_TRANSCRIPT = "video_transcript"
    SLIDE_PDF = "slide_pdf"
    EXERCISE = "exercise"


@dataclass(frozen=True)
class ContentVersion(ValueObject):
    """Immutable pointer to one object-storage version of a document."""

    number: int
    object_key: str
    object_version_id: str  # S3 version id - strict versioning requirement
    checksum_sha256: str
    published_at: datetime

    def __post_init__(self) -> None:
        if self.number < 1:
            raise InvariantViolation("version number starts at 1")


@dataclass(frozen=True)
class ChunkingStrategy(ValueObject):
    """Semantic chunking parameters (paragraph/section boundaries, not fixed windows)."""

    max_tokens: int = 512
    overlap_tokens: int = 64
    respect_headings: bool = True
    min_chunk_tokens: int = 64


@dataclass(eq=False, kw_only=True)
class Chunk(Entity[str]):
    content_id: ContentId
    version_number: int
    ordinal: int
    text: str
    section_path: tuple[str, ...] = ()  # e.g. ("Module 3", "Joins")
    start_offset: int = 0
    end_offset: int = 0
    embedding_ref: str | None = None  # vector index id, never the raw vector


@dataclass(eq=False, kw_only=True)
class ContentItem(AggregateRoot[ContentId]):
    course_id: CourseId
    content_type: ContentType
    title: str
    versions: list[ContentVersion] = field(default_factory=list)
    indexed_version: int | None = None

    @property
    def latest(self) -> ContentVersion | None:
        return self.versions[-1] if self.versions else None

    def publish_version(self, version: ContentVersion) -> None:
        if self.latest and version.number != self.latest.number + 1:
            raise InvariantViolation("versions must be sequential")
        self.versions.append(version)
        self.record(
            ContentVersionPublished(
                aggregate_id=self.id, course_id=self.course_id, version=version.number
            )
        )

    def mark_indexed(self, version_number: int, chunk_count: int) -> None:
        self.indexed_version = version_number
        self.record(
            ContentIndexed(aggregate_id=self.id, version=version_number, chunk_count=chunk_count)
        )
