from __future__ import annotations

from typing import Protocol

from edu_platform.contexts.content.domain.model import Chunk, ContentItem
from edu_platform.shared_kernel.domain.ids import ContentId


class ContentRepository(Protocol):
    def get(self, content_id: ContentId) -> ContentItem | None: ...

    def save(self, item: ContentItem) -> None: ...

    def all(self) -> list[ContentItem]: ...


class DocumentStore(Protocol):
    """Object storage with versioning (S3 / SeaweedFS locally)."""

    def put(self, object_key: str, body: str) -> str: ...  # returns version id

    def fetch(self, object_key: str, version_id: str) -> str: ...


class VectorIndex(Protocol):
    def upsert(self, chunks: list[Chunk]) -> None: ...

    def delete_version(self, content_id: ContentId, version: int) -> None: ...

    def count(self, content_id: ContentId) -> int: ...


class SearchIndexer(Protocol):
    def reindex(self, item: ContentItem) -> None: ...

    def indexed_version(self, content_id: ContentId) -> int | None: ...


class CacheInvalidator(Protocol):
    def invalidate(self, course_id: str, content_id: ContentId) -> None: ...

    def state(self, content_id: ContentId) -> str: ...  # "warm" | "invalidated"

    def warm(self, content_id: ContentId) -> None: ...
