from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from edu_platform.contexts.content.domain.model import Chunk, ContentItem
from edu_platform.shared_kernel.domain.ids import ContentId


class ContentRepository(Protocol):
    def get(self, content_id: ContentId) -> ContentItem | None: ...

    def save(self, item: ContentItem) -> None: ...

    def all(self) -> list[ContentItem]: ...


class DocumentStore(Protocol):
    """Object storage with versioning (S3/MinIO)."""

    def put(self, object_key: str, body: str) -> str: ...  # returns version id

    def fetch(self, object_key: str, version_id: str | None) -> str: ...  # None = latest


class Embedder(Protocol):
    """Text -> dense vector. ``model`` names the embedding space stored with every vector."""

    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorIndex(Protocol):
    def upsert(self, chunks: list[Chunk]) -> None: ...

    def delete_version(self, content_id: ContentId, version: int) -> None: ...

    def prune(self, content_id: ContentId, keep_version: int) -> None:
        """Drop the chunks of every other version (versions skipped by CDC included)."""
        ...

    def delete_content(self, content_id: ContentId) -> None: ...

    def count(self, content_id: ContentId) -> int: ...


class SearchIndexer(Protocol):
    def reindex(self, item: ContentItem) -> None: ...

    def indexed_version(self, content_id: ContentId) -> int | None: ...

    def remove(self, content_id: ContentId) -> None: ...


@dataclass(frozen=True)
class SearchHit:
    content_id: str
    version: int
    title: str
    ordinal: int
    section_path: tuple[str, ...]
    snippet: str
    score: float


class ContentSearch(Protocol):
    def search(self, course_id: str, query: str, *, limit: int, hybrid: bool) -> list[SearchHit]:
        """Current versions only. ``hybrid`` fuses keyword (BM25) and vector (kNN) ranks."""
        ...


class CacheInvalidator(Protocol):
    def invalidate(self, course_id: str, content_id: ContentId) -> None: ...

    def state(self, content_id: ContentId) -> str: ...  # "warm" | "invalidated"

    def warm(self, content_id: ContentId) -> None: ...


@dataclass(frozen=True)
class CatalogEntry:
    """The LMS ``course_content`` row: the current published version of one document."""

    content_id: str
    course_id: str
    content_type: str
    title: str
    version: int
    object_key: str
    duration_sec: int | None
    updated_at: datetime


class ContentCatalog(Protocol):
    """LMS source of truth for content versions (its changes reach the sync via CDC)."""

    def get(self, content_id: str) -> CatalogEntry | None: ...

    def for_course(self, course_id: str) -> list[CatalogEntry]: ...

    def publish_version(
        self, content_id: str, title: str | None, write: Callable[[str, int], str]
    ) -> CatalogEntry:
        """Lock the row, call ``write(course_id, next_version)`` (stores the document and
        returns its object key), then commit the new version. Raises KeyError if unknown."""
        ...
