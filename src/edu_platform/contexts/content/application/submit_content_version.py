"""Use case BR8 (write side): an instructor publishes a new version of a document.

Stores the body as a new immutable object and advances the LMS ``course_content`` row in
one locked step. Nothing else is synchronised here: the row change reaches the
content-sync service through CDC (Debezium -> Kafka), exactly like a change made by any
other LMS writer, so there is one sync path to operate and test.
"""

from __future__ import annotations

from dataclasses import dataclass

from edu_platform.contexts.content.application.ports import (
    CatalogEntry,
    ContentCatalog,
    DocumentStore,
)
from edu_platform.contexts.content.domain.model import object_key_for
from edu_platform.shared_kernel.domain import InvariantViolation, NotFoundError


@dataclass(frozen=True)
class SubmitContentVersionResult:
    entry: CatalogEntry
    changed: bool  # False: identical body and title, no new version


class SubmitContentVersion:
    def __init__(self, catalog: ContentCatalog, documents: DocumentStore) -> None:
        self._catalog = catalog
        self._documents = documents

    def execute(self, content_id: str, body: str, title: str | None) -> SubmitContentVersionResult:
        if not body.strip():
            raise InvariantViolation("a content version needs a non-empty body")
        current = self._catalog.get(content_id)
        if current is None:
            raise NotFoundError(f"content {content_id} not found")
        if (title in (None, current.title)) and self._same_body(current, body):
            return SubmitContentVersionResult(current, changed=False)

        def write(course_id: str, version: int) -> str:
            key = object_key_for(course_id, content_id, version)
            self._documents.put(key, body)
            return key

        entry = self._catalog.publish_version(content_id, title, write)
        return SubmitContentVersionResult(entry, changed=True)

    def _same_body(self, current: CatalogEntry, body: str) -> bool:
        try:
            return self._documents.fetch(current.object_key, None) == body
        except Exception:  # a missing or unreadable current object never blocks publishing
            return False
