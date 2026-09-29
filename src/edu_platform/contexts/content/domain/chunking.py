"""Domain service: semantic chunking of extracted text blocks.

Splits on paragraph/heading boundaries first, then packs paragraphs into
chunks under ``max_tokens`` with sentence-level overlap. Pure and deterministic.
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
            if (body and _tokens(body) >= strategy.min_chunk_tokens) or (body and not chunks):
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
            buffer = []

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
