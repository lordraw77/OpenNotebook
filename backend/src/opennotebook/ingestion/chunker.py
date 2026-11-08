"""Structure-aware chunking with overlap.

Blocks are split into units (sentences; very long sentences are split by words) that never cross block
boundaries. Units are packed greedily up to `size` tokens; a heading starts a new chunk when the current one
is already substantial; consecutive chunks share up to `overlap` tokens. Each chunk is a contiguous slice of
the document text, so `doc.text[chunk.char_start:chunk.char_end] == chunk.text` always holds.

Token counts are estimated (no tokenizer model is downloaded): max(words, characters / 4).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from opennotebook.ingestion.document import Block, ParsedDocument

_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+(?=[\"'(\[]?[A-ZÀ-ÖØ-Þ0-9])|\n+")
_WORD = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    words = len(_WORD.findall(text))
    return max(words, math.ceil(len(text) / 4)) if text else 0


@dataclass
class _Unit:
    start: int
    end: int
    tokens: int
    block: Block


@dataclass
class ChunkData:
    ordinal: int
    text: str
    char_start: int
    char_end: int
    token_count: int
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    line_start: int
    line_end: int
    bboxes: list[dict] = field(default_factory=list)
    block_type: str = "text"


def _units(doc: ParsedDocument, text: str, size: int) -> list[_Unit]:
    units: list[_Unit] = []
    for block in doc.blocks:
        if block.block_type in ("heading", "table", "code") and estimate_tokens(block.text) <= size:
            units.append(_Unit(block.char_start, block.char_end, estimate_tokens(block.text), block))
            continue
        cursor = block.char_start
        pieces: list[tuple[int, int]] = []
        for m in _SENTENCE_END.finditer(text, block.char_start, block.char_end):
            if m.start() > cursor:
                pieces.append((cursor, m.start()))
            cursor = m.end()
        if cursor < block.char_end:
            pieces.append((cursor, block.char_end))
        for s, e in pieces:
            tokens = estimate_tokens(text[s:e])
            if tokens <= size:
                units.append(_Unit(s, e, tokens, block))
                continue
            # Oversized sentence: split on word boundaries.
            words = list(_WORD.finditer(text, s, e))
            step = max(1, int(len(words) * size / tokens))
            for i in range(0, len(words), step):
                ws, we = words[i].start(), words[min(i + step, len(words)) - 1].end()
                units.append(_Unit(ws, we, estimate_tokens(text[ws:we]), block))
    return units


def chunk_document(doc: ParsedDocument, size: int = 512, overlap: int = 64) -> list[ChunkData]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("require 0 <= overlap < size")
    text = doc.text
    units = _units(doc, text, size)
    chunks: list[ChunkData] = []
    i = 0
    while i < len(units):
        j, tokens = i, 0
        while j < len(units):
            u = units[j]
            if j > i and tokens + u.tokens > size:
                break
            if j > i and u.block.block_type == "heading" and tokens >= size // 4:
                break
            # source code: a new symbol starts a new chunk once the current one is substantial
            if (
                j > i
                and u.block.block_type == "code"
                and u.block.heading_path
                and u.block is not units[j - 1].block
                and u.block.heading_path != units[j - 1].block.heading_path
                and tokens >= size // 4
            ):
                break
            tokens += u.tokens
            j += 1
        selected = units[i:j]
        chunks.append(_make_chunk(len(chunks), text, selected))
        if j >= len(units):
            break
        # Overlap: restart from the trailing units totalling at most `overlap` tokens (always make progress).
        k, back = j, 0
        while (
            k - 1 > i and back + units[k - 1].tokens <= overlap and units[k - 1].block.block_type != "heading"
        ):
            k -= 1
            back += units[k].tokens
        i = k
    return chunks


def _make_chunk(ordinal: int, text: str, units: list[_Unit]) -> ChunkData:
    start, end = units[0].start, units[-1].end
    blocks: list[Block] = []
    for u in units:
        if not blocks or blocks[-1] is not u.block:
            blocks.append(u.block)
    content = [b for b in blocks if b.block_type != "heading"] or blocks
    pages = [b.page for b in blocks if b.page is not None]
    bboxes = [box for b in blocks for box in b.bboxes]
    types = {b.block_type for b in content}
    first_line = text.count("\n", 0, start) + 1
    return ChunkData(
        ordinal=ordinal,
        text=text[start:end],
        char_start=start,
        char_end=end,
        token_count=estimate_tokens(text[start:end]),
        heading_path=list(_main_block(units, content).heading_path),
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        line_start=first_line,
        line_end=first_line + text.count("\n", start, end),
        bboxes=bboxes,
        block_type=types.pop() if len(types) == 1 else "mixed",
    )


def _main_block(units: list[_Unit], content: list[Block]) -> Block:
    """Prose: the first content block. Code: the block (symbol) contributing most tokens."""
    if any(b.block_type != "code" for b in content):
        return content[0]
    weight: dict[int, int] = {}
    for u in units:
        weight[id(u.block)] = weight.get(id(u.block), 0) + u.tokens
    return max(content, key=lambda b: (weight.get(id(b), 0), bool(b.heading_path)))


def embedding_text(title: str, chunk: ChunkData) -> str:
    """Text sent to the embedding model: a contextual header (source and section) followed by the chunk."""
    header = " > ".join([title, *chunk.heading_path])
    return f"{header}\n\n{chunk.text}"
