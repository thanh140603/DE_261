"""OpenSearchContentIndex against an in-memory fake of the OpenSearch API surface it uses.

The fake evaluates the query subset the adapter emits (term / bool filter, must_not,
should + minimum_should_match / match / knn with filter) so the adapter's behaviour is
tested: idempotent upserts, pruning, current-version scoping and hybrid fusion. Real
analyzers, HNSW and DSL validation need an OpenSearch node (docker profile br678).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from edu_platform.contexts.content.domain.chunking import SemanticChunker
from edu_platform.contexts.content.domain.model import (
    ChunkingStrategy,
    ContentItem,
    ContentType,
    ContentVersion,
)
from edu_platform.contexts.content.infrastructure.hashing_embedder import HashingEmbedder
from edu_platform.contexts.content.infrastructure.opensearch_index import (
    OpenSearchContentIndex,
    _fuse,
)
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId

pytest.importorskip("opensearchpy")


class _Indices:
    def __init__(self, store: dict[str, dict[str, dict[str, Any]]]) -> None:
        self._store = store
        self.created: dict[str, dict[str, Any]] = {}

    def exists(self, index: str) -> bool:
        return index in self._store

    def create(self, index: str, body: dict[str, Any]) -> None:
        self._store[index] = {}
        self.created[index] = body


class FakeOpenSearch:
    def __init__(self) -> None:
        from opensearchpy.serializer import JSONSerializer

        self.docs: dict[str, dict[str, dict[str, Any]]] = {}
        self.indices = _Indices(self.docs)
        self.transport = type("T", (), {"serializer": JSONSerializer()})()
        self.searches: list[dict[str, Any]] = []

    # documents
    def index(self, index: str, id: str, body: dict[str, Any], **_: Any) -> None:
        self.docs.setdefault(index, {})[id] = body

    def get(self, index: str, id: str, realtime: bool = True) -> dict[str, Any]:
        from opensearchpy.exceptions import NotFoundError

        if id not in self.docs.get(index, {}):
            raise NotFoundError(404, "not_found", {})
        return {"_source": self.docs[index][id]}

    def delete(self, index: str, id: str, **_: Any) -> None:
        from opensearchpy.exceptions import NotFoundError

        if id not in self.docs.get(index, {}):
            raise NotFoundError(404, "not_found", {})
        del self.docs[index][id]

    def bulk(self, body: str, **_: Any) -> dict[str, Any]:
        lines = [json.loads(line) for line in body.strip().split("\n")]
        items = []
        for action, source in zip(lines[::2], lines[1::2], strict=True):
            meta = action["index"]
            self.index(meta["_index"], meta["_id"], source)
            items.append({"index": {"_id": meta["_id"], "status": 201}})
        return {"errors": False, "items": items}

    # queries
    def _match(self, doc: dict[str, Any], q: dict[str, Any]) -> bool:
        if "term" in q:
            ((field, value),) = q["term"].items()
            return bool(doc.get(field) == value)
        if "bool" in q:
            b = q["bool"]
            ok = all(self._match(doc, c) for c in b.get("filter", []) + b.get("must", []))
            ok = ok and not any(self._match(doc, c) for c in b.get("must_not", []))
            if b.get("should"):
                hits = sum(self._match(doc, c) for c in b["should"])
                ok = ok and hits >= b.get("minimum_should_match", 1)
            return ok
        if "match" in q:
            ((field, text),) = q["match"].items()
            return bool(set(text.lower().split()) & set(str(doc.get(field, "")).lower().split()))
        if "match_all" in q:
            return True
        raise AssertionError(f"unsupported query {q}")

    def _score(self, doc: dict[str, Any], q: dict[str, Any]) -> float:
        must = q.get("bool", {}).get("must", [])
        if must and "match" in must[0]:
            ((field, text),) = must[0]["match"].items()
            words = str(doc.get(field, "")).lower().split()
            return float(sum(words.count(w) for w in text.lower().split()))
        return 0.0

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.searches.append({"index": index, "body": body})
        query = body["query"]
        docs = list(self.docs.get(index, {}).values())
        if "knn" in query:
            spec = query["knn"]["embedding"]
            docs = [d for d in docs if self._match(d, spec["filter"])]
            ranked = sorted(
                docs,
                key=lambda d: (
                    -sum(a * b for a, b in zip(d["embedding"], spec["vector"], strict=True))
                ),
            )[: spec["k"]]
        else:
            ranked = sorted(
                (d for d in docs if self._match(d, query)), key=lambda d: -self._score(d, query)
            )
        return {"hits": {"hits": [{"_source": d} for d in ranked[: body.get("size", 10)]]}}

    def count(self, index: str, body: dict[str, Any]) -> dict[str, int]:
        return {
            "count": sum(self._match(d, body["query"]) for d in self.docs.get(index, {}).values())
        }

    def delete_by_query(self, index: str, body: dict[str, Any], **_: Any) -> None:
        for doc_id, doc in list(self.docs.get(index, {}).items()):
            if self._match(doc, body["query"]):
                del self.docs[index][doc_id]


def item(content_id: str, course: str, title: str, version: int) -> ContentItem:
    return ContentItem(
        id=ContentId(content_id),
        course_id=CourseId(course),
        content_type=ContentType.VIDEO_TRANSCRIPT,
        title=title,
        versions=[
            ContentVersion(
                version, f"k/{version}", "latest", "sha", datetime(2026, 10, 1, tzinfo=UTC)
            )
        ],
    )


def chunks(content_id: str, version: int, text: str) -> Any:
    strategy = ChunkingStrategy(max_tokens=40, min_chunk_tokens=1)
    return SemanticChunker().chunk(ContentId(content_id), version, text, strategy)


JOINS_V1 = "# Joins\n\nAn inner join keeps only matching rows.\n\nUse ON to state the columns."
JOINS_V2 = (
    "# Joins\n\nA left join keeps every row of the left table.\n\nUnmatched columns are NULL."
)
LOOPS = "# Loops\n\nA for loop repeats a block for every item in a list."


@pytest.fixture
def index() -> OpenSearchContentIndex:
    idx = OpenSearchContentIndex(FakeOpenSearch(), HashingEmbedder(32))
    idx.ensure_indices()
    return idx


def publish(
    idx: OpenSearchContentIndex, content_id: str, course: str, title: str, version: int, text: str
) -> None:
    idx.upsert(chunks(content_id, version, text))
    idx.prune(ContentId(content_id), version)
    idx.reindex(item(content_id, course, title, version))


def test_mapping_declares_vector_dimensions(index: OpenSearchContentIndex) -> None:
    created = index._client.indices.created  # type: ignore[attr-defined]
    embedding = created["edu-content-chunks"]["mappings"]["properties"]["embedding"]
    assert embedding["type"] == "knn_vector" and embedding["dimension"] == 32
    assert created["edu-content-chunks"]["settings"]["index"]["knn"] is True


def test_upsert_is_idempotent_and_prune_keeps_only_one_version(
    index: OpenSearchContentIndex,
) -> None:
    cid = ContentId("v-sql-joins")
    index.upsert(chunks(cid, 1, JOINS_V1))
    first = index.count(cid)
    index.upsert(chunks(cid, 1, JOINS_V1))  # redelivery
    assert index.count(cid) == first > 0
    index.upsert(chunks(cid, 2, JOINS_V2))
    index.prune(cid, 2)
    docs = index._client.docs["edu-content-chunks"].values()  # type: ignore[attr-defined]
    assert {d["version"] for d in docs} == {2}
    assert all(d["embedding_model"] == "hashing-v1-32" and len(d["embedding"]) == 32 for d in docs)


def test_meta_marker_and_removal(index: OpenSearchContentIndex) -> None:
    cid = ContentId("v-sql-joins")
    assert index.indexed_version(cid) is None
    publish(index, cid, "c-sql-101", "Joins", 2, JOINS_V2)
    assert index.indexed_version(cid) == 2
    index.delete_content(cid)
    index.remove(cid)
    index.remove(cid)  # idempotent
    assert index.indexed_version(cid) is None and index.count(cid) == 0


def test_search_is_scoped_to_course_and_current_version(index: OpenSearchContentIndex) -> None:
    publish(index, "v-sql-joins", "c-sql-101", "Joins", 2, JOINS_V2)
    publish(index, "v-py-lists", "c-py-201", "Lists and loops", 1, LOOPS)
    # a lagging old chunk (prune not yet applied) must not be returned
    index.upsert(chunks("v-sql-joins", 1, JOINS_V1 + " left left left"))

    hits = index.search("c-sql-101", "left join", limit=5, hybrid=False)
    assert hits and {h.content_id for h in hits} == {"v-sql-joins"}
    assert {h.version for h in hits} == {2}
    assert hits[0].title == "Joins"
    assert index.search("c-sql-101", "loop", limit=5, hybrid=False) == []
    assert index.search("c-unknown", "left", limit=5, hybrid=False) == []
    assert index.search("c-sql-101", "   ", limit=5, hybrid=False) == []


def test_hybrid_adds_vector_ranking(index: OpenSearchContentIndex) -> None:
    publish(index, "v-sql-joins", "c-sql-101", "Joins", 2, JOINS_V2)
    hits = index.search("c-sql-101", "left join", limit=5, hybrid=True)
    bodies = [
        s["body"]["query"] for s in index._client.searches if s["index"] == "edu-content-chunks"
    ]  # type: ignore[attr-defined]
    assert any("knn" in q for q in bodies)
    assert hits and hits[0].content_id == "v-sql-joins"


def test_reciprocal_rank_fusion() -> None:
    def hit(chunk: str) -> dict[str, Any]:
        return {
            "_source": {
                "chunk_id": chunk,
                "content_id": "c",
                "version": 1,
                "ordinal": 0,
                "text": chunk,
            }
        }

    current = {"c": {"title": "T"}}
    fused = _fuse([[hit("a"), hit("b")], [hit("b"), hit("c")]], current, 3)
    assert [h.snippet for h in fused] == ["b", "a", "c"]  # b ranked by both lists wins
    assert _fuse([[hit("x"), hit("y")]], current, 1)[0].snippet == "x"
