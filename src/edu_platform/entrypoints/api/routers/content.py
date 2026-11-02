"""Scoped BR8 content APIs: publish a version, follow its sync, read through the cache, search.

Publishing only writes the LMS row + the versioned object (SubmitContentVersion); the
content-sync service picks the row change up through CDC, so ``in_sync`` turns true when
cache, vectors and the search entry have caught up. Same instructor tokens as BR4-BR7.
The demo endpoints (/instructor/content/{id}) are untouched.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Annotated, Any, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from edu_platform.br45.api import Principal, instructor
from edu_platform.contexts.content.application.ports import CatalogEntry, ContentCatalog
from edu_platform.contexts.content.application.submit_content_version import SubmitContentVersion
from edu_platform.contexts.content.infrastructure.opensearch_index import OpenSearchContentIndex
from edu_platform.contexts.content.infrastructure.postgres_content_catalog import (
    PostgresContentCatalog,
)
from edu_platform.contexts.content.infrastructure.redis_cache import RedisContentCache
from edu_platform.contexts.content.infrastructure.s3_document_store import S3DocumentStore
from edu_platform.entrypoints.services.content_sync.main import build_adapters
from edu_platform.platform.config import get_settings
from edu_platform.shared_kernel.domain.ids import ContentId

router = APIRouter(tags=["BR8 content sync"])
T = TypeVar("T")


class ContentUnavailable(Exception):
    """PostgreSQL, MinIO, Redis or OpenSearch could not be reached."""


@dataclass
class ContentServices:
    catalog: ContentCatalog
    documents: S3DocumentStore
    cache: RedisContentCache
    index: OpenSearchContentIndex


@lru_cache(maxsize=1)
def _services() -> ContentServices:
    settings = get_settings()
    adapters = build_adapters(settings)
    catalog = PostgresContentCatalog(settings.postgres_dsn.get_secret_value())
    return ContentServices(catalog, adapters.documents, adapters.cache, adapters.index)


def content_services() -> ContentServices:
    return _services()


Services = Annotated[ContentServices, Depends(content_services)]
Instructor = Annotated[Principal, Depends(instructor)]


@contextmanager
def _available() -> Iterator[None]:
    """Map infrastructure outages to 503; domain errors pass through to their handlers."""
    import psycopg
    import redis
    from botocore.exceptions import BotoCoreError, ClientError
    from opensearchpy.exceptions import ConnectionError as SearchConnectionError
    from opensearchpy.exceptions import TransportError

    try:
        yield
    except (
        psycopg.OperationalError,
        redis.exceptions.ConnectionError,
        BotoCoreError,
        ClientError,
        SearchConnectionError,
        TransportError,
    ) as exc:
        raise ContentUnavailable(str(exc)) from exc


def _call(fn: Callable[[], T]) -> T:
    with _available():
        return fn()


def _entry(services: ContentServices, user: Principal, content_id: str) -> CatalogEntry:
    entry = _call(lambda: services.catalog.get(content_id))
    if entry is None:
        raise HTTPException(404, f"Unknown content {content_id}")
    if entry.course_id not in user.courses:
        raise HTTPException(403, "Course is outside your authorized scope")
    return entry


def _status(services: ContentServices, entry: CatalogEntry) -> dict[str, Any]:
    cid = ContentId(entry.content_id)
    meta = _call(lambda: services.index.meta(cid, searchable=True))  # in_sync = searchable
    indexed = None if meta is None else int(meta["version"])
    return {
        **asdict(entry),
        "indexed_version": indexed,
        "indexed_at": None if meta is None else meta.get("indexed_at"),
        "chunk_count": _call(lambda: services.index.count(cid)),
        "cache_state": _call(lambda: services.cache.state(cid)),
        "in_sync": indexed == entry.version,
    }


@router.get("/instructor/courses/{course_id}/content")
def course_content(course_id: str, user: Instructor, services: Services) -> dict[str, Any]:
    if course_id not in user.courses:
        raise HTTPException(403, "Course is outside your authorized scope")
    entries = _call(lambda: services.catalog.for_course(course_id))
    return {"course_id": course_id, "items": [_status(services, e) for e in entries]}


@router.get("/instructor/content/{content_id}/sync-status")
def sync_status(content_id: str, user: Instructor, services: Services) -> dict[str, Any]:
    return _status(services, _entry(services, user, content_id))


class VersionBody(BaseModel):
    body: str = Field(min_length=1, max_length=500_000)
    title: str | None = Field(default=None, max_length=200)


@router.post("/instructor/content/{content_id}/versions", status_code=202)
def publish_version(
    content_id: str, payload: VersionBody, user: Instructor, services: Services
) -> dict[str, Any]:
    _entry(services, user, content_id)
    submit = SubmitContentVersion(services.catalog, services.documents)
    result = _call(lambda: submit.execute(content_id, payload.body, payload.title))
    return {
        **asdict(result.entry),
        "changed": result.changed,
        "status": "pending_sync" if result.changed else "unchanged",
    }


@router.get("/instructor/content/{content_id}/document")
def document(content_id: str, user: Instructor, services: Services) -> dict[str, Any]:
    """Read-through cache in front of object storage: shows invalidation working.

    Order matters: the generation is read before the catalog row, so a sync that lands
    while this request loads the old version makes ``put_document`` refuse to cache it.
    Scope is checked before the cache is consulted.
    """
    generation = _call(lambda: services.cache.generation(content_id))
    entry = _entry(services, user, content_id)
    cached = _call(lambda: services.cache.get_document(content_id))
    if cached is not None:
        return {**cached, "cache": "hit"}
    body = _call(lambda: services.documents.fetch(entry.object_key, None))
    payload = {
        "content_id": entry.content_id,
        "course_id": entry.course_id,
        "title": entry.title,
        "version": entry.version,
        "body": body,
    }
    _call(lambda: services.cache.put_document(content_id, payload, generation))
    return {**payload, "cache": "miss"}


@router.get("/instructor/courses/{course_id}/search")
def search(
    course_id: str,
    user: Instructor,
    services: Services,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    mode: Literal["keyword", "hybrid"] = "hybrid",
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict[str, Any]:
    if course_id not in user.courses:
        raise HTTPException(403, "Course is outside your authorized scope")
    hits = _call(lambda: services.index.search(course_id, q, limit=limit, hybrid=mode == "hybrid"))
    return {"course_id": course_id, "query": q, "mode": mode, "hits": [asdict(h) for h in hits]}
