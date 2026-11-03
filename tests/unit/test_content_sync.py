"""BR8 content sync: idempotency policy, SyncContentChange, CDC parsing and the adapters that
run without a server (S3 via moto, Redis via fakeredis, hashing embedder)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from edu_platform.contexts.content.application.ports import CatalogEntry
from edu_platform.contexts.content.application.submit_content_version import SubmitContentVersion
from edu_platform.contexts.content.application.sync_content_change import SyncContentChange
from edu_platform.contexts.content.domain.model import ContentType, object_key_for
from edu_platform.contexts.content.domain.sync_policy import ContentChange, SyncAction, decide
from edu_platform.contexts.content.infrastructure.debezium_content_change import (
    parse_content_change,
)
from edu_platform.contexts.content.infrastructure.hashing_embedder import HashingEmbedder
from edu_platform.contexts.content.infrastructure.in_memory import (
    InMemoryCacheInvalidator,
    InMemoryDocumentStore,
    InMemorySearchIndexer,
    InMemoryVectorIndex,
)
from edu_platform.shared_kernel.domain import InvariantViolation, NotFoundError
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId

T0 = datetime(2026, 10, 8, 7, 0, tzinfo=UTC)
JOINS_V1 = "# Joins\n\n" + " ".join(["An inner join keeps matching rows."] * 30)
JOINS_V2 = "# Joins\n\n" + " ".join(["A left join keeps every row of the left table."] * 30)


def change(version: int, **overrides: Any) -> ContentChange:
    values: dict[str, Any] = {
        "content_id": ContentId("v-sql-joins"),
        "course_id": CourseId("c-sql-101"),
        "content_type": ContentType.VIDEO_TRANSCRIPT,
        "title": "Joins",
        "version": version,
        "object_key": object_key_for("c-sql-101", "v-sql-joins", version),
        "changed_at": T0 + timedelta(days=version),
    }
    return ContentChange(**(values | overrides))


# --- policy -------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("version", "indexed", "force", "expected"),
    [
        (1, None, False, SyncAction.APPLY),
        (3, 2, False, SyncAction.APPLY),
        (2, 2, False, SyncAction.SKIP_DUPLICATE),
        (2, 2, True, SyncAction.APPLY),
        (1, 2, False, SyncAction.SKIP_STALE),
        (1, 2, True, SyncAction.SKIP_STALE),  # force never rolls search back
    ],
)
def test_sync_policy(version: int, indexed: int | None, force: bool, expected: SyncAction) -> None:
    assert decide(change(version), indexed, force=force) is expected


def test_removal_always_applies() -> None:
    assert decide(change(1, deleted=True), 5) is SyncAction.REMOVE


def test_change_invariants() -> None:
    with pytest.raises(InvariantViolation):
        change(0)
    with pytest.raises(InvariantViolation):
        change(1, object_key="")


# --- use case -------------------------------------------------------------------------
class Harness:
    def __init__(self, publisher: Any) -> None:
        self.documents = InMemoryDocumentStore()
        self.cache = InMemoryCacheInvalidator()
        self.vectors = InMemoryVectorIndex()
        self.search = InMemorySearchIndexer()
        self.publisher = publisher
        self.sync = SyncContentChange(
            self.documents, self.cache, self.vectors, self.search, publisher
        )

    def store(self, version: int, body: str) -> None:
        self.documents.put(object_key_for("c-sql-101", "v-sql-joins", version), body)


@pytest.fixture
def h(publisher: Any) -> Harness:
    harness = Harness(publisher)
    harness.store(1, JOINS_V1)
    harness.store(2, JOINS_V2)
    return harness


def events(h: Harness) -> list[tuple[str, int]]:
    return [(e.event_type, e.version) for _, e in h.publisher.published]  # type: ignore[attr-defined]


def test_new_version_syncs_everything(h: Harness) -> None:
    result = h.sync.execute(change(1))
    assert result.action is SyncAction.APPLY
    assert [s.step for s in result.steps] == [
        "fetch versioned document",
        "invalidate cache",
        "semantic chunking + embedding",
        "refresh search index",
        "warm cache",
    ]
    assert h.search.indexed_version(ContentId("v-sql-joins")) == 1
    assert h.vectors.count(ContentId("v-sql-joins")) == result.chunk_count > 0
    assert h.cache.invalidations == [("c-sql-101", "v-sql-joins")]
    assert h.cache.state(ContentId("v-sql-joins")) == "warm"
    assert events(h) == [("content.version_published.v1", 1), ("content.indexed.v1", 1)]


def test_next_version_replaces_vectors_of_every_older_version(h: Harness) -> None:
    h.sync.execute(change(1))
    h.sync.execute(change(2))
    versions = {c.version_number for c in h.vectors.chunks.values()}
    assert versions == {2}
    assert "left join" in " ".join(c.text for c in h.vectors.chunks.values())


def test_replays_and_stale_changes_are_no_ops(h: Harness) -> None:
    h.sync.execute(change(2))
    before = len(h.publisher.published)  # type: ignore[attr-defined]
    for replay in (change(2), change(1)):  # duplicate delivery, then an old snapshot
        result = h.sync.execute(replay)
        assert result.action in (SyncAction.SKIP_DUPLICATE, SyncAction.SKIP_STALE)
        assert [s.status for s in result.steps] == ["skipped"]
    assert h.search.indexed_version(ContentId("v-sql-joins")) == 2
    assert len(h.publisher.published) == before  # type: ignore[attr-defined]


def test_forced_reindex_does_not_republish_the_version(h: Harness) -> None:
    h.sync.execute(change(1))
    h.sync.execute(change(1), force=True)
    assert events(h) == [
        ("content.version_published.v1", 1),
        ("content.indexed.v1", 1),
        ("content.indexed.v1", 1),
    ]


def test_skipped_versions_are_pruned(h: Harness) -> None:
    h.store(3, JOINS_V1 + "\n\nThird cut.")
    h.sync.execute(change(1))
    h.sync.execute(change(3))  # v2 never seen by the sync (e.g. compacted topic)
    assert {c.version_number for c in h.vectors.chunks.values()} == {3}


def test_removal(h: Harness) -> None:
    h.sync.execute(change(2))
    result = h.sync.execute(change(2, deleted=True))
    assert result.action is SyncAction.REMOVE
    assert h.vectors.count(ContentId("v-sql-joins")) == 0
    assert h.search.indexed_version(ContentId("v-sql-joins")) is None
    assert h.cache.state(ContentId("v-sql-joins")) == "invalidated"


def test_event_payloads_match_the_warehouse_contract(h: Harness) -> None:
    h.sync.execute(change(2))
    published, indexed = (e.to_payload() for _, e in h.publisher.published)  # type: ignore[attr-defined]
    # warehouse/transform/silver/content_sync_events.sql reads exactly these fields
    for payload in (published, indexed):
        assert {"event_id", "event_type", "aggregate_id", "occurred_at", "version"} <= set(payload)
        assert payload["aggregate_id"] == "v-sql-joins"
    assert published["course_id"] == "c-sql-101"
    assert published["occurred_at"] == (T0 + timedelta(days=2)).isoformat()  # LMS publish time
    assert indexed["chunk_count"] > 0


# --- CDC parsing ---------------------------------------------------------------------------
ROW = {
    "content_id": "v-sql-joins",
    "course_id": "c-sql-101",
    "content_type": "video_transcript",
    "title": "Joins",
    "version": 2,
    "object_key": "courses/c-sql-101/v-sql-joins/v2.md",
    "duration_sec": 390,
    "updated_at": "2026-10-10T07:00:00.123456Z",
    "__op": "u",
    "__deleted": "false",
    "__source_lsn": 123,
}


def test_parse_unwrapped_and_enveloped_rows() -> None:
    for value in (ROW, {"schema": {"type": "struct"}, "payload": ROW}):
        parsed = parse_content_change(value)
        assert parsed is not None
        assert (parsed.version, parsed.deleted) == (2, False)
        assert parsed.changed_at == datetime(2026, 10, 10, 7, 0, 0, 123456, tzinfo=UTC)


def test_parse_delete_and_epoch_time_and_heartbeat() -> None:
    deleted = parse_content_change(ROW | {"__deleted": "true", "updated_at": 1791622800000})
    assert deleted is not None and deleted.deleted
    assert deleted.changed_at.tzinfo is not None
    assert parse_content_change({"schema": {}, "payload": None}) is None
    assert parse_content_change({"ts_ms": 1}) is None


def test_parse_rejects_unknown_content_type() -> None:
    with pytest.raises(ValueError):
        parse_content_change(ROW | {"content_type": "podcast"})


# --- embedder ----------------------------------------------------------------------------
def test_hashing_embedder_is_deterministic_and_normalised() -> None:
    embedder = HashingEmbedder(64)
    a, b, c = embedder.embed(["inner join rows", "inner join rows", "python list loops"])
    assert a == b and len(a) == 64
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9
    close = embedder.embed_one("an inner join keeps matching rows")
    assert sum(x * y for x, y in zip(a, close, strict=True)) > sum(
        x * y for x, y in zip(c, close, strict=True)
    )
    assert embedder.embed([""])[0] == [0.0] * 64


# --- S3 (moto) ----------------------------------------------------------------------------
@pytest.fixture
def s3() -> Iterator[Any]:
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    with moto.mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="corpus")
        client.put_bucket_versioning(Bucket="corpus", VersioningConfiguration={"Status": "Enabled"})
        yield client


def test_s3_store_reads_exact_versions(s3: Any) -> None:
    from edu_platform.contexts.content.infrastructure.s3_document_store import (
        DocumentNotFound,
        S3DocumentStore,
    )

    store = S3DocumentStore(s3, "corpus")
    first = store.put("courses/c/x/doc.md", "first")
    second = store.put("courses/c/x/doc.md", "second")
    assert first != second
    assert store.fetch("courses/c/x/doc.md", first) == "first"
    assert store.fetch("courses/c/x/doc.md", None) == "second"
    with pytest.raises(DocumentNotFound):
        store.fetch("courses/c/x/missing.md", None)


# --- Redis (fakeredis) ----------------------------------------------------------------------
def test_redis_cache_invalidation_and_generation_guard() -> None:
    fakeredis = pytest.importorskip("fakeredis")
    from edu_platform.contexts.content.infrastructure.redis_cache import RedisContentCache

    client = fakeredis.FakeRedis(decode_responses=True)
    cache = RedisContentCache(client)
    cid = ContentId("v-sql-joins")
    assert cache.state(cid) == "warm"
    generation = cache.generation(cid)
    assert cache.put_document(cid, {"version": 1}, generation)
    client.set("edu:cache:course:c-sql-101:outline", "{}")

    cache.invalidate("c-sql-101", cid)
    assert cache.state(cid) == "invalidated"
    assert cache.get_document(cid) is None
    assert client.get("edu:cache:course:c-sql-101:outline") is None
    # a reader that loaded before the invalidation must not re-cache the old version
    assert not cache.put_document(cid, {"version": 1}, generation)
    cache.warm(cid)
    assert cache.state(cid) == "warm"
    assert cache.put_document(cid, {"version": 2}, cache.generation(cid))
    assert cache.get_document(cid) == {"version": 2}


# --- write side ---------------------------------------------------------------------------
class FakeCatalog:
    def __init__(self) -> None:
        self.rows = {
            "v-sql-joins": CatalogEntry(
                "v-sql-joins", "c-sql-101", "video_transcript", "Joins", 1,
                object_key_for("c-sql-101", "v-sql-joins", 1), 420, T0,
            )
        }  # fmt: skip

    def get(self, content_id: str) -> CatalogEntry | None:
        return self.rows.get(content_id)

    def for_course(self, course_id: str) -> list[CatalogEntry]:
        return [r for r in self.rows.values() if r.course_id == course_id]

    def publish_version(
        self, content_id: str, title: str | None, write: Callable[[str, int], str]
    ) -> CatalogEntry:
        row = self.rows[content_id]
        key = write(row.course_id, row.version + 1)
        new = CatalogEntry(
            row.content_id, row.course_id, row.content_type, title or row.title,
            row.version + 1, key, row.duration_sec, T0 + timedelta(hours=1),
        )  # fmt: skip
        self.rows[content_id] = new
        return new


def test_submit_writes_a_new_immutable_object_per_version() -> None:
    catalog, documents = FakeCatalog(), InMemoryDocumentStore()
    documents.put(object_key_for("c-sql-101", "v-sql-joins", 1), JOINS_V1)
    submit = SubmitContentVersion(catalog, documents)

    result = submit.execute("v-sql-joins", JOINS_V2, None)
    assert result.changed and result.entry.version == 2
    assert result.entry.object_key == "courses/c-sql-101/v-sql-joins/v2.md"
    assert documents.fetch(result.entry.object_key, None) == JOINS_V2
    assert documents.fetch(object_key_for("c-sql-101", "v-sql-joins", 1), None) == JOINS_V1

    same = submit.execute("v-sql-joins", JOINS_V2, "Joins")
    assert not same.changed and same.entry.version == 2
    retitled = submit.execute("v-sql-joins", JOINS_V2, "Joins (re-recorded)")
    assert retitled.changed and retitled.entry.version == 3


def test_submit_rejects_unknown_and_empty() -> None:
    submit = SubmitContentVersion(FakeCatalog(), InMemoryDocumentStore())
    with pytest.raises(NotFoundError):
        submit.execute("v-missing", "text", None)
    with pytest.raises(InvariantViolation):
        submit.execute("v-sql-joins", "   ", None)
