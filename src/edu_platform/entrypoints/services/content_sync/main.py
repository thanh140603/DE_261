"""Content Sync Service (BR8) - keeps cache, search index and embeddings consistent.

Content (TODO):
- Consume lms.course_updated.v1 + cdc.lms.public.course_content -> SyncContentChange.
- Consume object-storage notifications (new object version) -> IngestContentDocument.
- Emits content.updated.v1 for downstream consumers (e.g. notification rule
  "content updated" for enrolled learners).
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    main()
