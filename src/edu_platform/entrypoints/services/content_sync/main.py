"""Content Sync Service (BR8) - keeps cache, search index and embeddings consistent.

Consumes Debezium CDC of the LMS ``course_content`` table (``cdc.lms.public.course_content``;
a new version is a row update pointing at a new object in the versioned corpus bucket) and
runs SyncContentChange: fetch the document, invalidate Redis caches, chunk + embed into
OpenSearch, refresh the search entry, warm the cache. Emits ``content.updated.v1`` and
``content.indexed.v1`` (landed in bronze -> gold.fct_content_sync for the sync SLA).

At least once: the input offset is committed only after the sync and the produced events
are acknowledged; replays are no-ops (domain.sync_policy). Poison records go to
``cdc.lms.public.course_content.dlq`` after 3 attempts.

  edu service content-sync
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from edu_platform.contexts.content.application.sync_content_change import SyncContentChange
from edu_platform.contexts.content.infrastructure.debezium_content_change import (
    parse_content_change,
)
from edu_platform.contexts.content.infrastructure.hashing_embedder import HashingEmbedder
from edu_platform.contexts.content.infrastructure.opensearch_index import (
    OpenSearchContentIndex,
    create_opensearch_client,
)
from edu_platform.contexts.content.infrastructure.redis_cache import RedisContentCache
from edu_platform.contexts.content.infrastructure.s3_document_store import S3DocumentStore
from edu_platform.platform.config import Settings, get_settings
from edu_platform.platform.logging import get_logger
from edu_platform.platform.messaging.kafka_consumer import KafkaConsumerLoop, KafkaMessage
from edu_platform.platform.messaging.kafka_producer import KafkaEventPublisher
from edu_platform.platform.messaging.topics import Topic
from edu_platform.platform.storage.object_storage import create_s3_client
from edu_platform.platform.storage.redis_client import create_redis_client
from edu_platform.shared_kernel.application import EventPublisher

log = get_logger(__name__)


@dataclass
class ContentAdapters:
    documents: S3DocumentStore
    cache: RedisContentCache
    index: OpenSearchContentIndex


def build_adapters(settings: Settings) -> ContentAdapters:
    """Composition root shared by the service, the reindex job and the instructor API."""
    return ContentAdapters(
        documents=S3DocumentStore(create_s3_client(settings.lakehouse), settings.corpus_bucket),
        cache=RedisContentCache(create_redis_client(settings.redis_url)),
        index=OpenSearchContentIndex(
            create_opensearch_client(settings.search_url), HashingEmbedder()
        ),
    )


def build_sync(adapters: ContentAdapters, publisher: EventPublisher) -> SyncContentChange:
    return SyncContentChange(
        adapters.documents, adapters.cache, adapters.index, adapters.index, publisher
    )


def handler(sync: SyncContentChange, flush: Any) -> Any:
    def handle(message: KafkaMessage) -> None:
        change = parse_content_change(message.payload)
        if change is None:
            return
        result = sync.execute(change)
        flush()  # events acknowledged before the loop commits the input offset
        log.info(
            "content change synced",
            content_id=result.content_id,
            version=result.version,
            action=result.action.value,
            previous=result.previous_version,
            chunks=result.chunk_count,
            ms=sum(s.ms for s in result.steps),
        )

    return handle


def main() -> None:
    logging.getLogger("opensearch").setLevel(logging.WARNING)  # one line per HTTP call otherwise
    settings = get_settings()
    adapters = build_adapters(settings)
    adapters.index.ensure_indices()
    publisher = KafkaEventPublisher(settings.kafka.bootstrap_servers, client_id="edu-content-sync")
    loop = KafkaConsumerLoop(
        settings.kafka.bootstrap_servers,
        group_id="edu-content-sync",
        topics=[Topic.CDC_COURSE_CONTENT.value],
        dlq_publisher=lambda topic, payload: publisher.publish_raw(
            topic, key=None, payload=payload
        ),
    )
    log.info("content sync started", topic=Topic.CDC_COURSE_CONTENT.value)
    try:
        loop.run(handler(build_sync(adapters, publisher), publisher.flush))
    finally:
        publisher.close()


if __name__ == "__main__":
    main()
