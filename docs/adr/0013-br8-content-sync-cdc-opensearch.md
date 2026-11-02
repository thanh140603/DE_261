# ADR 0013: BR8 content sync is driven by CDC of course_content into OpenSearch

Status: accepted - 2026-11-02 (implements the BR8 part of the BR6/BR7/BR8 plan)

## Context
BR8 asks that caches are invalidated and the search index refreshed when course content
changes, over a versioned corpus that needs semantic chunking. The demo ran every step
in-process inside the request that published the content. In production a version can be
published by any LMS writer, CDC delivers at least once and may replay old snapshots, and
the PDF names Spark for large-scale chunking/embedding.

## Decision
- **One sync path.** A new version is a `public.course_content` row update pointing at a new
  immutable object (`courses/<course>/<content>/v<n>.<ext>`, versioned bucket). Debezium
  captures it; the `content-sync` service runs `SyncContentChange`: fetch, invalidate Redis
  caches, chunk + embed, prune other versions, refresh the search entry, warm, publish
  `content.updated.v1` / `content.indexed.v1` (-> `gold.fct_content_sync` SLA). The instructor
  API only writes the object and the row (`SubmitContentVersion`, row lock); it never syncs.
- **Idempotency by index state, not arrival order** (`domain.sync_policy`): apply only a
  version newer than the indexed one; equal = duplicate (unless forced), older = stale.
  The OpenSearch meta document is the marker; search only returns chunks of each item's
  current version, so a lagging prune never surfaces old text.
- **OpenSearch** holds chunks (BM25 text + Lucene HNSW `knn_vector`) and per-item metadata;
  hybrid ranking fuses keyword and vector ranks client-side (reciprocal rank fusion), which
  needs no search pipeline plugin.
- **Embeddings** come from a deterministic hashing embedder behind an `Embedder` port
  (no model download, no GPU). Vectors carry the model name; a real sentence-embedding model
  is a new adapter plus a forced reindex.
- **Spark backfill** (`edu batch content-reindex`) distributes the *same* use case per item
  slice (forced) and writes `silver.content_chunks`; no second chunking implementation.

## Consequences
- Content published by any writer is synchronised; replays, restarts and backfills are safe.
- Search freshness = Debezium capture + consumer lag (seconds); readers see the old version
  until the sync invalidates the cache, never a partially indexed new one.
- The hashing embedder is lexical: "join" does not match "merge". Semantic quality needs a
  model adapter; the interface and reindex path already exist.
- Fixing chunking to never drop short sections (it silently discarded about two thirds of
  every transcript) changes chunk ids for existing content; run a forced reindex once.
