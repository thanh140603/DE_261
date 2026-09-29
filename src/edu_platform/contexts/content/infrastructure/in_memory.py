"""In-memory content adapters (tests + demo). S3/OpenSearch/Redis adapters are TODO."""

from __future__ import annotations

from collections import defaultdict

from edu_platform.contexts.content.domain.model import Chunk, ContentItem
from edu_platform.shared_kernel.domain.ids import ContentId


class InMemoryContentRepository:
    def __init__(self) -> None:
        self._rows: dict[str, ContentItem] = {}

    def get(self, content_id: ContentId) -> ContentItem | None:
        return self._rows.get(content_id)

    def save(self, item: ContentItem) -> None:
        self._rows[item.id] = item

    def all(self) -> list[ContentItem]:
        return list(self._rows.values())


class InMemoryDocumentStore:
    def __init__(self) -> None:
        self._versions: dict[str, list[str]] = defaultdict(list)

    def put(self, object_key: str, body: str) -> str:
        self._versions[object_key].append(body)
        return f"v{len(self._versions[object_key])}"

    def fetch(self, object_key: str, version_id: str) -> str:
        return self._versions[object_key][int(version_id[1:]) - 1]


class InMemoryVectorIndex:
    def __init__(self) -> None:
        self.chunks: dict[str, Chunk] = {}

    def upsert(self, chunks: list[Chunk]) -> None:
        for c in chunks:
            self.chunks[c.id] = c

    def delete_version(self, content_id: ContentId, version: int) -> None:
        for k in [
            k
            for k, c in self.chunks.items()
            if c.content_id == content_id and c.version_number == version
        ]:
            del self.chunks[k]

    def count(self, content_id: ContentId) -> int:
        return sum(c.content_id == content_id for c in self.chunks.values())


class InMemorySearchIndexer:
    def __init__(self) -> None:
        self._versions: dict[str, int] = {}

    def reindex(self, item: ContentItem) -> None:
        if item.latest:
            self._versions[item.id] = item.latest.number

    def indexed_version(self, content_id: ContentId) -> int | None:
        return self._versions.get(content_id)


class InMemoryCacheInvalidator:
    def __init__(self) -> None:
        self._state: dict[str, str] = {}
        self.invalidations: list[tuple[str, str]] = []

    def invalidate(self, course_id: str, content_id: ContentId) -> None:
        self._state[content_id] = "invalidated"
        self.invalidations.append((course_id, content_id))

    def state(self, content_id: ContentId) -> str:
        return self._state.get(content_id, "warm")

    def warm(self, content_id: ContentId) -> None:
        self._state[content_id] = "warm"
