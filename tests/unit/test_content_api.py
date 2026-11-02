"""BR8 end to end through the real code paths, without servers:

instructor POST -> SubmitContentVersion -> S3 (moto, versioned) + catalog row
-> Debezium-shaped record -> content-sync service handler -> SyncContentChange
-> Redis (fakeredis) + OpenSearch (in-memory fake) -> status / document / search APIs.

PostgreSQL (catalog) and Kafka/Debezium are replaced by FakeCatalog and a record built
the way the connector emits it; tests/e2e covers them against the docker stack.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict
from typing import Any

import pytest
from fastapi.testclient import TestClient

from edu_platform.br45.config import settings as br45_settings
from edu_platform.contexts.content.domain.model import object_key_for
from edu_platform.contexts.content.infrastructure.hashing_embedder import HashingEmbedder
from edu_platform.contexts.content.infrastructure.opensearch_index import OpenSearchContentIndex
from edu_platform.contexts.content.infrastructure.redis_cache import RedisContentCache
from edu_platform.contexts.content.infrastructure.s3_document_store import S3DocumentStore
from edu_platform.entrypoints.api.main import create_app
from edu_platform.entrypoints.api.routers.content import ContentServices, content_services
from edu_platform.entrypoints.services.content_sync.main import (
    ContentAdapters,
    build_sync,
    handler,
)
from edu_platform.platform.messaging.kafka_consumer import KafkaMessage
from tests.unit.test_content_sync import JOINS_V1, FakeCatalog
from tests.unit.test_opensearch_index import FakeOpenSearch

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")
fakeredis = pytest.importorskip("fakeredis")

TOKENS = {
    "teacher": {"id": "inst-1", "role": "instructor", "courses": ["c-sql-101"]},
    "other": {"id": "inst-2", "role": "instructor", "courses": ["c-py-201"]},
}
H = {"Authorization": "Bearer teacher"}
NEW_BODY = (
    "# Joins\n\nA left join keeps every row of the left table, matched or not.\n\n"
    "Columns from the right table are NULL when no row matches."
)


class Stack:
    def __init__(self, s3: Any, publisher: Any) -> None:
        self.catalog = FakeCatalog()
        self.documents = S3DocumentStore(s3, "corpus")
        self.cache = RedisContentCache(fakeredis.FakeRedis(decode_responses=True))
        self.index = OpenSearchContentIndex(FakeOpenSearch(), HashingEmbedder(32))
        self.index.ensure_indices()
        self.publisher = publisher
        adapters = ContentAdapters(self.documents, self.cache, self.index)
        self.handle = handler(build_sync(adapters, publisher), lambda: None)
        self.offset = 0

    def cdc(self, content_id: str, deleted: bool = False) -> None:
        """Deliver the current catalog row the way Debezium (unwrap + JsonConverter) does."""
        row = asdict(self.catalog.rows[content_id])
        row["updated_at"] = row["updated_at"].isoformat().replace("+00:00", "Z")
        value = {"schema": {"type": "struct"}, "payload": row | {
            "__op": "d" if deleted else "u", "__deleted": str(deleted).lower()}}  # fmt: skip
        self.offset += 1
        message = KafkaMessage("cdc.lms.public.course_content", content_id, value, 0, self.offset)
        self.handle(message)


@pytest.fixture
def stack(publisher: Any) -> Iterator[Stack]:
    with moto.mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="corpus")
        s3.put_bucket_versioning(Bucket="corpus", VersioningConfiguration={"Status": "Enabled"})
        s3.put_object(
            Bucket="corpus", Key=object_key_for("c-sql-101", "v-sql-joins", 1), Body=JOINS_V1
        )
        yield Stack(s3, publisher)


@pytest.fixture
def client(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("EDU_BR45_AUTH", json.dumps(TOKENS))
    br45_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[content_services] = lambda: ContentServices(
        stack.catalog, stack.documents, stack.cache, stack.index
    )
    yield TestClient(app)
    br45_settings.cache_clear()


def status(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/instructor/content/v-sql-joins/sync-status", headers=H)
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_publish_then_cdc_sync_end_to_end(client: TestClient, stack: Stack) -> None:
    stack.cdc("v-sql-joins")  # initial snapshot of v1
    assert status(client)["in_sync"] and status(client)["indexed_version"] == 1
    first = client.get("/api/instructor/content/v-sql-joins/document", headers=H).json()
    assert first["cache"] == "miss" and first["version"] == 1
    assert (
        client.get("/api/instructor/content/v-sql-joins/document", headers=H).json()["cache"]
        == "hit"
    )

    posted = client.post(
        "/api/instructor/content/v-sql-joins/versions", headers=H, json={"body": NEW_BODY}
    )
    assert posted.status_code == 202
    assert posted.json()["version"] == 2 and posted.json()["status"] == "pending_sync"
    pending = status(client)
    assert pending["version"] == 2 and pending["indexed_version"] == 1 and not pending["in_sync"]
    # until the sync runs, readers still get the cached v1 (the sync is what invalidates)
    assert (
        client.get("/api/instructor/content/v-sql-joins/document", headers=H).json()["version"] == 1
    )

    stack.cdc("v-sql-joins")  # Debezium delivers the row update
    synced = status(client)
    assert synced["in_sync"] and synced["indexed_version"] == 2
    assert synced["cache_state"] == "warm" and synced["chunk_count"] > 0
    fresh = client.get("/api/instructor/content/v-sql-joins/document", headers=H).json()
    assert fresh["cache"] == "miss" and fresh["version"] == 2 and fresh["body"] == NEW_BODY

    hits = client.get(
        "/api/instructor/courses/c-sql-101/search", headers=H, params={"q": "left join"}
    ).json()["hits"]
    assert hits and all(h["version"] == 2 for h in hits)
    assert "left join" in hits[0]["snippet"].lower()
    old = client.get(
        "/api/instructor/courses/c-sql-101/search",
        headers=H,
        params={"q": "inner", "mode": "keyword"},
    ).json()["hits"]
    assert old == []  # v1 text is gone from search

    types = [e.event_type for _, e in stack.publisher.published]
    assert types == ["content.version_published.v1", "content.indexed.v1"] * 2


def test_replayed_cdc_record_changes_nothing(client: TestClient, stack: Stack) -> None:
    stack.cdc("v-sql-joins")
    before = (status(client), len(stack.publisher.published))
    stack.cdc("v-sql-joins")  # at-least-once redelivery
    assert (status(client), len(stack.publisher.published)) == before


def test_unchanged_publish_creates_no_version(client: TestClient) -> None:
    response = client.post(
        "/api/instructor/content/v-sql-joins/versions", headers=H, json={"body": JOINS_V1}
    )
    assert response.status_code == 202
    assert response.json()["changed"] is False and response.json()["version"] == 1


def test_scope_and_validation(client: TestClient) -> None:
    other = {"Authorization": "Bearer other"}
    for method, path, body in (
        ("get", "/api/instructor/content/v-sql-joins/sync-status", None),
        ("get", "/api/instructor/content/v-sql-joins/document", None),
        ("post", "/api/instructor/content/v-sql-joins/versions", {"body": "x"}),
        ("get", "/api/instructor/courses/c-sql-101/search?q=join", None),
        ("get", "/api/instructor/courses/c-sql-101/content", None),
    ):
        kwargs: dict[str, Any] = {"headers": other} | ({"json": body} if body else {})
        assert getattr(client, method)(path, **kwargs).status_code == 403, path
    assert client.get("/api/instructor/content/v-missing/sync-status", headers=H).status_code == 404
    empty = client.post(
        "/api/instructor/content/v-sql-joins/versions", headers=H, json={"body": ""}
    )
    assert empty.status_code == 422
    assert client.get("/api/instructor/content/v-sql-joins/sync-status").status_code == 401


def test_cached_document_is_not_served_outside_scope(client: TestClient, stack: Stack) -> None:
    stack.cdc("v-sql-joins")
    client.get("/api/instructor/content/v-sql-joins/document", headers=H)  # warm the cache
    other = {"Authorization": "Bearer other"}
    assert (
        client.get("/api/instructor/content/v-sql-joins/document", headers=other).status_code == 403
    )


def test_course_listing(client: TestClient, stack: Stack) -> None:
    stack.cdc("v-sql-joins")
    body = client.get("/api/instructor/courses/c-sql-101/content", headers=H).json()
    (item,) = body["items"]
    assert item["content_id"] == "v-sql-joins" and item["in_sync"]


def test_outage_is_503(client: TestClient, stack: Stack) -> None:
    import redis

    def down(*_: Any, **__: Any) -> Any:
        raise redis.exceptions.ConnectionError("redis down")

    stack.cache.state = down  # type: ignore[method-assign]
    response = client.get("/api/instructor/content/v-sql-joins/sync-status", headers=H)
    assert response.status_code == 503
