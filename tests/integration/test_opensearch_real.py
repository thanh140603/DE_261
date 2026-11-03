"""OpenSearchContentIndex against a real OpenSearch node (analyzers, HNSW, DSL validation).

  docker compose --profile br678 up -d opensearch
  EDU_SEARCH_URL=http://localhost:9200 \
    uv run pytest -m integration tests/integration/test_opensearch_real.py

Uses throwaway index names, deleted afterwards.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from edu_platform.contexts.content.infrastructure.hashing_embedder import HashingEmbedder
from edu_platform.contexts.content.infrastructure.opensearch_index import (
    OpenSearchContentIndex,
    create_opensearch_client,
)
from edu_platform.shared_kernel.domain.ids import ContentId
from tests.unit.test_opensearch_index import JOINS_V1, JOINS_V2, LOOPS, chunks, item

pytestmark = pytest.mark.integration
URL = os.getenv("EDU_SEARCH_URL", "http://localhost:9200")


@pytest.fixture
def index() -> Iterator[OpenSearchContentIndex]:
    client: Any = create_opensearch_client(URL)
    try:
        client.info()
    except Exception:
        pytest.skip(f"OpenSearch not reachable at {URL}")
    suffix = uuid.uuid4().hex[:8]
    idx = OpenSearchContentIndex(
        client,
        HashingEmbedder(64),
        chunks_index=f"test-chunks-{suffix}",
        meta_index=f"test-meta-{suffix}",
    )
    idx.ensure_indices()
    idx.ensure_indices()  # idempotent
    yield idx
    client.indices.delete(index=f"test-chunks-{suffix},test-meta-{suffix}")


def publish(
    idx: OpenSearchContentIndex, cid: str, course: str, title: str, v: int, text: str
) -> None:
    idx.upsert(chunks(cid, v, text))
    idx.prune(ContentId(cid), v)
    idx.reindex(item(cid, course, title, v))


def test_versions_prune_and_marker(index: OpenSearchContentIndex) -> None:
    cid = ContentId("v-sql-joins")
    publish(index, cid, "c-sql-101", "Joins", 1, JOINS_V1)
    assert index.indexed_version(cid) == 1 and index.count(cid) > 0
    publish(index, cid, "c-sql-101", "Joins", 2, JOINS_V2)
    assert index.indexed_version(cid) == 2
    hits = index.search("c-sql-101", "inner join", limit=5, hybrid=False)
    assert all(h.version == 2 for h in hits)  # v1 chunks pruned
    index.delete_content(cid)
    index.remove(cid)
    index.remove(cid)
    assert index.indexed_version(cid) is None and index.count(cid) == 0


def test_keyword_search_uses_the_english_analyzer(index: OpenSearchContentIndex) -> None:
    publish(index, "v-sql-joins", "c-sql-101", "Joins", 2, JOINS_V2)
    publish(index, "v-py-lists", "c-py-201", "Lists and loops", 1, LOOPS)
    # "keeping" stems to "keep" (english analyzer); course scoping excludes the python video
    hits = index.search("c-sql-101", "keeping rows", limit=5, hybrid=False)
    assert hits and hits[0].content_id == "v-sql-joins" and hits[0].title == "Joins"
    assert index.search("c-sql-101", "loop", limit=5, hybrid=False) == []


def test_lagging_old_chunks_are_never_returned(index: OpenSearchContentIndex) -> None:
    publish(index, "v-sql-joins", "c-sql-101", "Joins", 2, JOINS_V2)
    index.upsert(chunks("v-sql-joins", 1, JOINS_V1 + " table table table"))  # not pruned yet
    for hybrid in (False, True):
        hits = index.search("c-sql-101", "table", limit=10, hybrid=hybrid)
        assert hits and {h.version for h in hits} == {2}


def test_hybrid_knn_query_is_accepted_and_filtered(index: OpenSearchContentIndex) -> None:
    publish(index, "v-sql-joins", "c-sql-101", "Joins", 2, JOINS_V2)
    publish(index, "v-py-lists", "c-py-201", "Lists and loops", 1, LOOPS)
    hits = index.search("c-sql-101", "left join keeps every row", limit=5, hybrid=True)
    assert hits and {h.content_id for h in hits} == {"v-sql-joins"}
