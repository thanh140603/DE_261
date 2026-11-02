"""Domain service: semantic chunking of extracted text blocks.

Splits on paragraph/heading boundaries first, then packs paragraphs into
chunks under ``max_tokens``. Pure and deterministic.

No text is ever dropped: a piece shorter than ``min_chunk_tokens`` is merged into the
previous chunk of the same section when it fits under ``max_tokens``, and otherwise kept
as its own chunk (a short section is still searchable; a heading is never crossed).
"""

from __future__ import annotations

import re

from edu_platform.shared_kernel.domain.ids import ContentId

from .model import Chunk, ChunkingStrategy

_HEADING = re.compile(r"^#+\s+(.*)$")


def _tokens(text: str) -> int:
    return len(text.split())


class SemanticChunker:
    def chunk(
        self, content_id: ContentId, version: int, text: str, strategy: ChunkingStrategy
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        section: tuple[str, ...] = ()
        buffer: list[str] = []
        offset = 0
        start = 0

        def flush() -> None:
            nonlocal buffer, start
            body = "\n\n".join(buffer).strip()
            buffer = []
            if not body:
                return
            last = chunks[-1] if chunks else None
            if (
                last is not None
                and _tokens(body) < strategy.min_chunk_tokens
                and last.section_path == section
                and _tokens(last.text) + _tokens(body) <= strategy.max_tokens
            ):
                last.text = f"{last.text}\n\n{body}"
                last.end_offset = start + len(body)
                return
            chunks.append(
                Chunk(
                    id=f"{content_id}:v{version}:{len(chunks)}",
                    content_id=content_id,
                    version_number=version,
                    ordinal=len(chunks),
                    text=body,
                    section_path=section,
                    start_offset=start,
                    end_offset=start + len(body),
                )
            )

        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            if not para:
                continue
            heading = _HEADING.match(para)
            if heading and strategy.respect_headings:
                flush()
                section = (heading.group(1).strip(),)
                start = offset
                offset += len(para) + 2
                continue
            if buffer and _tokens("\n\n".join(buffer)) + _tokens(para) > strategy.max_tokens:
                flush()
                start = offset
            if not buffer:
                start = offset
            buffer.append(para)
            offset += len(para) + 2
        flush()
        return chunks
