"""Content context: unstructured corpus + course-change synchronisation (BR8).

- Ingest transcripts / slide PDFs / exercises from object storage with strict
  versioning; extract layout, semantic-chunk, embed (Spark batch) and index.
- React to course_updated / CDC course_content changes: invalidate caches,
  refresh the search index and re-embed only the changed version.
"""
