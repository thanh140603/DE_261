"""VectorIndex + SearchIndexer + ContentSearch on OpenSearch (BR8 search refresh).

Two indices:
  edu-content-chunks  one document per chunk (id = chunk id, so re-upserts are idempotent):
                      text (BM25), embedding (knn_vector, Lucene HNSW), content_id, version
  edu-content-meta    one document per content item = the *current* indexed version; this
                      is the marker SyncContentChange compares new changes against

Queries join through the meta index and only return chunks of each item's current version,
so a lagging prune or an in-flight reindex never surfaces an old version.

Writes use ``refresh=True`` (refresh the shard now) rather than ``wait_for`` (wait for the
next 1 s scheduled refresh): content edits are rare, and a sync is then searchable within
milliseconds instead of ~2 s. Revisit for bulk loads (the reindex job) at large scale.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

from edu_platform.contexts.content.application.ports import Embedder, SearchHit
from edu_platform.contexts.content.domain.model import Chunk, ContentItem
from edu_platform.shared_kernel.domain.ids import ContentId

CHUNKS_INDEX = "edu-content-chunks"
META_INDEX = "edu-content-meta"
_RRF_K = 60  # reciprocal rank fusion constant


def create_opensearch_client(url: str) -> Any:
    from opensearchpy import OpenSearch

    return OpenSearch(hosts=[url], timeout=15, max_retries=2, retry_on_timeout=True)


class OpenSearchContentIndex:
    def __init__(
        self,
        client: Any,
        embedder: Embedder,
        *,
        chunks_index: str = CHUNKS_INDEX,
        meta_index: str = META_INDEX,
    ) -> None:
        self._client = client
        self._embedder = embedder
        self._chunks = chunks_index
        self._meta = meta_index

    @property
    def embedding_model(self) -> str:
        return self._embedder.model

    # --- bootstrap ----------------------------------------------------------------------
    def ensure_indices(self) -> None:
        if not self._client.indices.exists(index=self._chunks):
            self._client.indices.create(index=self._chunks, body=self.chunks_mapping())
        if not self._client.indices.exists(index=self._meta):
            self._client.indices.create(index=self._meta, body=META_MAPPING)

    def chunks_mapping(self) -> dict[str, Any]:
        return {
            "settings": {"index": {"knn": True, "number_of_shards": 1}},
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "content_id": {"type": "keyword"},
                    "version": {"type": "integer"},
                    "ordinal": {"type": "integer"},
                    "section_path": {"type": "keyword"},
                    "text": {"type": "text", "analyzer": "english"},
                    "embedding_model": {"type": "keyword"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": self._embedder.dimensions,
                        # vectors are L2-normalised, so l2 ranks exactly like cosine
                        "method": {"name": "hnsw", "engine": "lucene", "space_type": "l2"},
                    },
                }
            },
        }

    # --- VectorIndex --------------------------------------------------------------------
    def upsert(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        from opensearchpy import helpers

        vectors = self._embedder.embed([c.text for c in chunks])
        actions = [
            {
                "_op_type": "index",
                "_index": self._chunks,
                "_id": c.id,
                "_source": {
                    "chunk_id": c.id,
                    "content_id": c.content_id,
                    "version": c.version_number,
                    "ordinal": c.ordinal,
                    "section_path": list(c.section_path),
                    "text": c.text,
                    "embedding_model": self._embedder.model,
                    "embedding": v,
                },
            }
            for c, v in zip(chunks, vectors, strict=True)
        ]
        helpers.bulk(self._client, actions, refresh=True)

    def _delete(
        self, *filters: dict[str, Any], must_not: list[dict[str, Any]] | None = None
    ) -> None:
        query = {"bool": {"filter": list(filters), "must_not": must_not or []}}
        self._client.delete_by_query(
            index=self._chunks, body={"query": query}, refresh=True, conflicts="proceed"
        )

    def delete_version(self, content_id: ContentId, version: int) -> None:
        self._delete({"term": {"content_id": content_id}}, {"term": {"version": version}})

    def prune(self, content_id: ContentId, keep_version: int) -> None:
        self._delete(
            {"term": {"content_id": content_id}}, must_not=[{"term": {"version": keep_version}}]
        )

    def delete_content(self, content_id: ContentId) -> None:
        self._delete({"term": {"content_id": content_id}})

    def count(self, content_id: ContentId) -> int:
        body = {"query": {"term": {"content_id": content_id}}}
        return int(self._client.count(index=self._chunks, body=body)["count"])

    # --- SearchIndexer --------------------------------------------------------------------
    def reindex(self, item: ContentItem) -> None:
        latest = item.latest
        if latest is None:
            return
        self._client.index(
            index=self._meta,
            id=item.id,
            body={
                "content_id": item.id,
                "course_id": item.course_id,
                "title": item.title,
                "content_type": item.content_type.value,
                "version": latest.number,
                "object_key": latest.object_key,
                "checksum_sha256": latest.checksum_sha256,
                "published_at": latest.published_at.isoformat(),
                "indexed_at": datetime.now(tz=UTC).isoformat(),
                "embedding_model": self._embedder.model,
            },
            refresh=True,
        )

    def meta(self, content_id: str, *, searchable: bool = False) -> dict[str, Any] | None:
        """The indexed-version marker. ``searchable=True`` reads at search visibility (last
        refresh) instead of real time, so callers never report a version search cannot see."""
        from opensearchpy.exceptions import NotFoundError

        try:
            doc = self._client.get(index=self._meta, id=content_id, realtime=not searchable)
            return dict(doc["_source"])
        except NotFoundError:
            return None

    def indexed_version(self, content_id: ContentId) -> int | None:
        meta = self.meta(content_id)
        return None if meta is None else int(meta["version"])

    def remove(self, content_id: ContentId) -> None:
        from opensearchpy.exceptions import NotFoundError

        with contextlib.suppress(NotFoundError):
            self._client.delete(index=self._meta, id=content_id, refresh=True)

    # --- ContentSearch ----------------------------------------------------------------------
    def current_versions(self, course_id: str) -> dict[str, dict[str, Any]]:
        body = {"size": 1000, "query": {"term": {"course_id": course_id}}}
        hits = self._client.search(index=self._meta, body=body)["hits"]["hits"]
        return {h["_source"]["content_id"]: h["_source"] for h in hits}

    def search(self, course_id: str, query: str, *, limit: int, hybrid: bool) -> list[SearchHit]:
        current = self.current_versions(course_id)
        if not current or not query.strip():
            return []
        scope = {
            "bool": {
                "should": [
                    {
                        "bool": {
                            "filter": [
                                {"term": {"content_id": cid}},
                                {"term": {"version": meta["version"]}},
                            ]
                        }
                    }
                    for cid, meta in current.items()
                ],
                "minimum_should_match": 1,
            }
        }
        source = ["chunk_id", "content_id", "version", "ordinal", "section_path", "text"]
        keyword = self._client.search(
            index=self._chunks,
            body={
                "size": limit,
                "_source": source,
                "query": {"bool": {"must": [{"match": {"text": query}}], "filter": [scope]}},
            },
        )["hits"]["hits"]
        ranked: list[list[dict[str, Any]]] = [keyword]
        if hybrid:
            vector = self._embedder.embed([query])[0]
            knn = {"vector": vector, "k": limit, "filter": scope}
            ranked.append(
                self._client.search(
                    index=self._chunks,
                    body={"size": limit, "_source": source, "query": {"knn": {"embedding": knn}}},
                )["hits"]["hits"]
            )
        return _fuse(ranked, current, limit)


def _fuse(
    rankings: list[list[dict[str, Any]]], current: dict[str, dict[str, Any]], limit: int
) -> list[SearchHit]:
    """Reciprocal rank fusion (a single ranking keeps its order)."""
    scores: dict[str, float] = {}
    docs: dict[str, dict[str, Any]] = {}
    for hits in rankings:
        for rank, hit in enumerate(hits, start=1):
            src = hit["_source"]
            scores[src["chunk_id"]] = scores.get(src["chunk_id"], 0.0) + 1.0 / (_RRF_K + rank)
            docs[src["chunk_id"]] = src
    ordered = sorted(scores, key=lambda cid: -scores[cid])[:limit]
    return [
        SearchHit(
            content_id=docs[c]["content_id"],
            version=int(docs[c]["version"]),
            title=str(current[docs[c]["content_id"]]["title"]),
            ordinal=int(docs[c]["ordinal"]),
            section_path=tuple(docs[c].get("section_path") or ()),
            snippet=_snippet(str(docs[c]["text"])),
            score=round(scores[c], 6),
        )
        for c in ordered
    ]


def _snippet(text: str, size: int = 240) -> str:
    text = " ".join(text.split())
    return text if len(text) <= size else text[: size - 1].rsplit(" ", 1)[0] + "…"


META_MAPPING: dict[str, Any] = {
    "settings": {"index": {"number_of_shards": 1}},
    "mappings": {
        "properties": {
            "content_id": {"type": "keyword"},
            "course_id": {"type": "keyword"},
            "title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "content_type": {"type": "keyword"},
            "version": {"type": "integer"},
            "object_key": {"type": "keyword"},
            "checksum_sha256": {"type": "keyword"},
            "published_at": {"type": "date"},
            "indexed_at": {"type": "date"},
            "embedding_model": {"type": "keyword"},
        }
    },
}
