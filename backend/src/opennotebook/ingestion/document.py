"""Unified document model produced by every parser and consumed by the chunker.

The document text is the concatenation of block texts separated by blank lines. Every block records its
character offsets in that text, its line range, page and bounding boxes, so chunks can be traced back to the
exact position in the original source (citations and highlighting).
"""

from __future__ import annotations

from dataclasses import dataclass, field

BLOCK_SEPARATOR = "\n\n"


@dataclass
class Block:
    text: str
    block_type: str  # heading | paragraph | table | list | code
    heading_path: tuple[str, ...] = ()
    heading_level: int = 0  # 1..6 for headings
    page: int | None = None  # 1-based
    bboxes: list[dict] = field(default_factory=list)  # [{page, x0, top, x1, bottom}] in PDF points
    char_start: int = 0
    char_end: int = 0
    line_start: int = 0  # 1-based, in the document text
    line_end: int = 0


@dataclass
class ParsedDocument:
    title: str
    blocks: list[Block] = field(default_factory=list)
    page_count: int | None = None
    page_sizes: list[dict] = field(default_factory=list)  # [{page, width, height}]
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return BLOCK_SEPARATOR.join(b.text for b in self.blocks)


class DocumentBuilder:
    """Collects blocks, tracks the heading hierarchy and computes offsets."""

    def __init__(self, title: str) -> None:
        self.doc = ParsedDocument(title=title)
        self._headings: list[tuple[int, str]] = []
        self._pos = 0
        self._line = 1

    def heading(self, text: str, level: int, **kw: object) -> None:
        text = text.strip()
        if not text:
            return
        while self._headings and self._headings[-1][0] >= level:
            self._headings.pop()
        self._headings.append((level, text))
        self._add(text, "heading", heading_level=level, **kw)

    def block(self, text: str, block_type: str = "paragraph", **kw: object) -> None:
        text = text.strip("\n")
        if text.strip():
            self._add(text, block_type, **kw)

    def _add(self, text: str, block_type: str, **kw: object) -> None:
        if self.doc.blocks:
            self._pos += len(BLOCK_SEPARATOR)
            self._line += BLOCK_SEPARATOR.count("\n")
        lines = text.count("\n")
        block = Block(
            text=text,
            block_type=block_type,
            heading_path=tuple(h for _, h in self._headings),
            char_start=self._pos,
            char_end=self._pos + len(text),
            line_start=self._line,
            line_end=self._line + lines,
            **kw,  # type: ignore[arg-type]
        )
        self.doc.blocks.append(block)
        self._pos = block.char_end
        self._line = block.line_end

    def build(self) -> ParsedDocument:
        return self.doc
