"""Use case: register a new document version and synchronise everything that
depends on it (corpus ingestion + BR8 sync).

Steps, each idempotent on (content_id, version):
1. store body in versioned object storage, compute checksum; identical -> skip.
2. item.publish_version(...) -> ContentVersionPublished.
3. invalidate course/content caches.
4. re-chunk (semantic) and re-embed only this version; drop previous vectors.
5. refresh search index; item.mark_indexed -> ContentIndexed.
Returns a step log so operators (and the demo UI) can see what was synced.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime

from edu_platform.contexts.content.application.ports import (
    CacheInvalidator,
    ContentRepository,
    DocumentStore,
    SearchIndexer,
    VectorIndex,
)
from edu_platform.contexts.content.domain.chunking import SemanticChunker
from edu_platform.contexts.content.domain.model import ChunkingStrategy, ContentVersion
from edu_platform.shared_kernel.application import EventPublisher
from edu_platform.shared_kernel.domain import NotFoundError
from edu_platform.shared_kernel.domain.ids import ContentId


@dataclass(frozen=True)
class PublishContentVersionCommand:
    content_id: str
    body: str
    title: str | None
    published_at: datetime


@dataclass
class SyncStep:
    step: str
    status: str  # done | skipped
    ms: int


@dataclass
class PublishContentVersionResult:
    version: int
    steps: list[SyncStep] = field(default_factory=list)
    chunk_count: int = 0


class PublishContentVersion:
    def __init__(
        self,
        repo: ContentRepository,
        documents: DocumentStore,
        cache: CacheInvalidator,
        vectors: VectorIndex,
        search: SearchIndexer,
        publisher: EventPublisher,
        chunker: SemanticChunker | None = None,
        strategy: ChunkingStrategy | None = None,
    ) -> None:
        self._repo = repo
        self._documents = documents
        self._cache = cache
        self._vectors = vectors
        self._search = search
        self._publisher = publisher
        self._chunker = chunker or SemanticChunker()
        self._strategy = strategy or ChunkingStrategy()

    def execute(self, command: PublishContentVersionCommand) -> PublishContentVersionResult:
        content_id = ContentId(command.content_id)
        item = self._repo.get(content_id)
        if item is None:
            raise NotFoundError(f"content {command.content_id} not found")
        checksum = hashlib.sha256(command.body.encode("utf-8")).hexdigest()
        latest = item.latest
        if latest and latest.checksum_sha256 == checksum and command.title in (None, item.title):
            return PublishContentVersionResult(
                version=latest.number, steps=[SyncStep("detect change", "skipped", 0)]
            )
        result = PublishContentVersionResult(version=(latest.number + 1) if latest else 1)
        if command.title:
            item.title = command.title
        with _Timed(result, "store versioned document"):
            key = f"{item.course_id}/{content_id}.md"
            version_id = self._documents.put(key, command.body)
            item.publish_version(
                ContentVersion(result.version, key, version_id, checksum, command.published_at)
            )
        with _Timed(result, "invalidate cache"):
            self._cache.invalidate(item.course_id, content_id)
        with _Timed(result, "semantic chunking + embedding"):
            chunks = self._chunker.chunk(content_id, result.version, command.body, self._strategy)
            if latest:
                self._vectors.delete_version(content_id, latest.number)
            self._vectors.upsert(chunks)
            result.chunk_count = len(chunks)
        with _Timed(result, "refresh search index"):
            self._search.reindex(item)
            item.mark_indexed(result.version, len(chunks))
        with _Timed(result, "warm cache"):
            self._cache.warm(content_id)
        self._repo.save(item)
        self._publisher.publish(item.pull_events())
        return result


class _Timed:
    def __init__(self, result: PublishContentVersionResult, step: str) -> None:
        self._result, self._step = result, step

    def __enter__(self) -> None:
        self._t0 = time.perf_counter()

    def __exit__(self, *exc: object) -> None:
        ms = int((time.perf_counter() - self._t0) * 1000)
        self._result.steps.append(SyncStep(self._step, "done", ms))
