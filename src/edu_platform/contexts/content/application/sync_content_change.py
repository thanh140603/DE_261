"""Use case BR8: synchronise cache, chunks/vectors and search with one captured content change.

Driven by CDC on the LMS ``course_content`` table (content-sync service) and by the corpus
reindex job. The document body already lives in versioned object storage; this use case
never writes it. Steps for a newer version (see domain.sync_policy for when they run):
1. fetch the document version from object storage,
2. invalidate the course/content caches (readers stop serving the old version at once),
3. semantic chunking + embedding of this version, then prune every other version's vectors,
4. refresh the search index entry (the version marker the policy compares against),
5. warm the cache; publish ContentVersionPublished (event time = LMS publish time, only for a
   version the index had not seen) and ContentIndexed -> gold.fct_content_sync SLA.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from edu_platform.contexts.content.application.ports import (
    CacheInvalidator,
    DocumentStore,
    SearchIndexer,
    VectorIndex,
)
from edu_platform.contexts.content.application.publish_content_version import SyncStep, _Timed
from edu_platform.contexts.content.domain.chunking import SemanticChunker
from edu_platform.contexts.content.domain.events import ContentVersionPublished
from edu_platform.contexts.content.domain.model import (
    Chunk,
    ChunkingStrategy,
    ContentItem,
    ContentVersion,
)
from edu_platform.contexts.content.domain.sync_policy import ContentChange, SyncAction, decide
from edu_platform.shared_kernel.application import EventPublisher


@dataclass
class SyncContentChangeResult:
    content_id: str
    version: int
    action: SyncAction
    previous_version: int | None
    chunk_count: int = 0
    steps: list[SyncStep] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)  # what was indexed (lineage writers)


class SyncContentChange:
    def __init__(
        self,
        documents: DocumentStore,
        cache: CacheInvalidator,
        vectors: VectorIndex,
        search: SearchIndexer,
        publisher: EventPublisher,
        chunker: SemanticChunker | None = None,
        strategy: ChunkingStrategy | None = None,
    ) -> None:
        self._documents = documents
        self._cache = cache
        self._vectors = vectors
        self._search = search
        self._publisher = publisher
        self._chunker = chunker or SemanticChunker()
        self._strategy = strategy or ChunkingStrategy()

    def execute(self, change: ContentChange, *, force: bool = False) -> SyncContentChangeResult:
        previous = self._search.indexed_version(change.content_id)
        action = decide(change, previous, force=force)
        result = SyncContentChangeResult(change.content_id, change.version, action, previous)
        if action in (SyncAction.SKIP_DUPLICATE, SyncAction.SKIP_STALE):
            result.steps.append(SyncStep(f"detect change ({action.value})", "skipped", 0))
            return result
        if action is SyncAction.REMOVE:
            with _Timed(result, "invalidate cache"):
                self._cache.invalidate(change.course_id, change.content_id)
            with _Timed(result, "remove vectors and search entry"):
                self._vectors.delete_content(change.content_id)
                self._search.remove(change.content_id)
            return result

        with _Timed(result, "fetch versioned document"):
            body = self._documents.fetch(change.object_key, change.object_version_id)
        with _Timed(result, "invalidate cache"):
            self._cache.invalidate(change.course_id, change.content_id)
        with _Timed(result, "semantic chunking + embedding"):
            chunks = self._chunker.chunk(change.content_id, change.version, body, self._strategy)
            self._vectors.upsert(chunks)  # upsert first: search never sees an empty document
            self._vectors.prune(change.content_id, change.version)
            result.chunk_count = len(chunks)
            result.chunks = chunks
        item = _item(change, body)
        with _Timed(result, "refresh search index"):
            self._search.reindex(item)
            item.mark_indexed(change.version, len(chunks))
        with _Timed(result, "warm cache"):
            self._cache.warm(change.content_id)
        events = item.pull_events()
        if previous is None or change.version > previous:
            published = ContentVersionPublished(
                aggregate_id=change.content_id,
                course_id=change.course_id,
                version=change.version,
                occurred_at=change.changed_at,
            )
            events = [published, *events]
        self._publisher.publish(events)
        return result


def _item(change: ContentChange, body: str) -> ContentItem:
    """The aggregate as the search index sees it: the single current version."""
    checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return ContentItem(
        id=change.content_id,
        course_id=change.course_id,
        content_type=change.content_type,
        title=change.title,
        versions=[
            ContentVersion(
                number=change.version,
                object_key=change.object_key,
                object_version_id=change.object_version_id or "latest",
                checksum_sha256=checksum,
                published_at=change.changed_at,
            )
        ],
    )
