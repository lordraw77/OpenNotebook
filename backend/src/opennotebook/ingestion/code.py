"""Structure-aware parsing of source code with tree-sitter (a deterministic parser, no ML).

The document text is the original file (verbatim mode), so chunk line numbers are file line numbers.
Blocks are the top-level definitions (functions, classes, structs, ...) with the comments right above them,
and the code between definitions (imports, globals). A large class is split into its header and its members,
each with the heading path `Class > member`. Files in languages without a grammar are split into
paragraphs (blank-line separated), still with exact lines.
"""

from __future__ import annotations

import importlib
import re
from functools import lru_cache
from typing import Any

from opennotebook.ingestion.chunker import estimate_tokens
from opennotebook.ingestion.document import Block, ParsedDocument
from opennotebook.ingestion.languages import GRAMMARS

_DEFINITION = re.compile(
    r"^(decorated_definition|"
    r"(function|method|class|struct|enum|union|interface|trait|impl|module|namespace|type|record|"
    r"protocol|object|constructor|singleton_method|singleton_class|type_alias)"
    r"_(definition|declaration|item|specifier|signature))$"
)
_CONTAINER_BODIES = ("body", "declaration_list", "class_body", "field_declaration_list")
_WRAPPERS = ("export_statement", "template_declaration", "declaration")
MAX_FILE_CHARS = 2_000_000


@lru_cache
def _parser(language: str) -> Any | None:
    spec = GRAMMARS.get(language)
    if spec is None:
        return None
    import tree_sitter

    module = importlib.import_module(spec[0])
    return tree_sitter.Parser(tree_sitter.Language(getattr(module, spec[1])()))


def _is_definition(node: Any) -> bool:
    if _DEFINITION.match(node.type):
        return True
    if node.type in _WRAPPERS:
        return any(_DEFINITION.match(c.type) for c in node.named_children)
    return False


def _name(node: Any, source: bytes) -> str:
    for candidate in (node, *node.named_children):
        name = candidate.child_by_field_name("name")
        if name is None:
            declarator = candidate.child_by_field_name("declarator")
            while declarator is not None and name is None:
                if declarator.type in ("identifier", "field_identifier", "qualified_identifier"):
                    name = declarator
                    break
                name = declarator.child_by_field_name("name")
                declarator = declarator.child_by_field_name("declarator")
        if name is not None:
            return source[name.start_byte : name.end_byte].decode("utf-8", "replace")[:120]
    return node.type.replace("_", " ")


_KINDS = (
    "class",
    "struct",
    "interface",
    "trait",
    "enum",
    "union",
    "impl",
    "module",
    "namespace",
    "record",
    "type",
)


def symbol_kind(node: Any) -> str:
    """function | class | struct | interface | ... from the tree-sitter node type (wrappers unwrapped)."""
    types = [node.type, *(c.type for c in node.named_children if _DEFINITION.match(c.type))]
    for t in types:
        for k in _KINDS:
            if t.startswith(k + "_") or t.startswith("singleton_" + k):
                return k
    return "function"


def _members(node: Any) -> list[Any]:
    """Definitions directly inside a class-like node."""
    target = node
    for c in node.named_children:  # decorated / exported / template wrappers
        if _DEFINITION.match(c.type) and c is not node:
            target = c
    body = target.child_by_field_name("body")
    if body is None:
        body = next((c for c in target.named_children if c.type in _CONTAINER_BODIES), None)
    if body is None:
        return []
    return [c for c in body.named_children if _is_definition(c)]


class _Offsets:
    """UTF-8 byte offsets (tree-sitter) to character offsets (Python strings)."""

    def __init__(self, source: bytes) -> None:
        self.source = source
        self._cache: dict[int, int] = {0: 0}

    def char(self, byte: int) -> int:
        if byte not in self._cache:
            below = max(b for b in self._cache if b <= byte)
            self._cache[byte] = self._cache[below] + len(self.source[below:byte].decode("utf-8", "replace"))
        return self._cache[byte]


def parse_code(text: str, language: str | None, title: str, chunk_tokens: int = 512) -> ParsedDocument:
    doc = ParsedDocument(title=title, raw_text=text, language=language)
    if len(text) > MAX_FILE_CHARS:
        doc.warnings.append("File larger than 2 MB: indexed by lines without structure")
        _paragraph_blocks(doc, text, 0, len(text), ())
        return _finish(doc)
    parser = _parser(language) if language else None
    if parser is None:
        _paragraph_blocks(doc, text, 0, len(text), ())
        return _finish(doc)

    source = text.encode("utf-8")
    tree = parser.parse(source)
    off = _Offsets(source)
    spans: list[tuple[int, int, tuple[str, ...], str | None]] = []  # byte spans
    code_start: int | None = None  # code not yet assigned (imports, globals, ...)
    comments_start: int | None = None  # comments after that code
    for node in tree.root_node.named_children:
        if node.type == "comment":
            if comments_start is None:
                comments_start = node.start_byte
            continue
        if not _is_definition(node):
            if code_start is None:
                code_start = comments_start if comments_start is not None else node.start_byte
            comments_start = None
            continue
        # comments right above a definition (no blank line in between) document it
        start = node.start_byte
        if comments_start is not None and b"\n\n" not in source[comments_start:start].replace(b"\r", b""):
            start = comments_start
        elif comments_start is not None and code_start is None:
            code_start = comments_start
        if code_start is not None:
            spans.append((code_start, start, (), None))
        code_start = comments_start = None
        name = _name(node, source)
        members = _members(node)
        size = estimate_tokens(source[start : node.end_byte].decode("utf-8", "replace"))
        kind = symbol_kind(node)
        if members and size > chunk_tokens:
            spans.append((start, members[0].start_byte, (name,), kind))
            cursor = members[0].start_byte
            for m in members:
                spans.append((cursor, m.end_byte, (name, _name(m, source)), symbol_kind(m)))
                cursor = m.end_byte
            if cursor < node.end_byte:
                spans.append((cursor, node.end_byte, (name,), None))
        else:
            spans.append((start, node.end_byte, (name,), kind))
            # members of a small class are still symbols of the graph (not separate blocks)
            for m in members:
                doc.symbols.append(
                    (name, _name(m, source), symbol_kind(m), off.char(m.start_byte), off.char(m.end_byte))
                )
    rest = code_start if code_start is not None else comments_start
    if rest is not None:
        spans.append((rest, len(source), (), None))

    for start, end, path, kind in spans:
        cs, ce = off.char(start), off.char(end)
        segment = text[cs:ce]
        stripped = segment.strip()
        if not stripped:
            continue
        lead = len(segment) - len(segment.lstrip())
        cs, ce = cs + lead, cs + lead + len(stripped)
        doc.blocks.append(
            Block(
                text=text[cs:ce],
                block_type="code",
                heading_path=path,
                char_start=cs,
                char_end=ce,
                symbol_kind=kind,
            )
        )
    if not doc.blocks:
        _paragraph_blocks(doc, text, 0, len(text), ())
    return _finish(doc)


_BLANK = re.compile(r"\n[ \t]*\n")


def _paragraph_blocks(doc: ParsedDocument, text: str, start: int, end: int, path: tuple[str, ...]) -> None:
    cursor = start
    for m in list(_BLANK.finditer(text, start, end)) + [None]:
        stop = m.start() if m else end
        segment = text[cursor:stop]
        if segment.strip():
            lead = len(segment) - len(segment.lstrip())
            cs = cursor + lead
            ce = cs + len(segment.strip())
            doc.blocks.append(
                Block(text=text[cs:ce], block_type="code", heading_path=path, char_start=cs, char_end=ce)
            )
        if m:
            cursor = m.end()


def _finish(doc: ParsedDocument) -> ParsedDocument:
    from opennotebook.ingestion.parsers import ParseError

    text = doc.text
    for b in doc.blocks:
        b.line_start = text.count("\n", 0, b.char_start) + 1
        b.line_end = b.line_start + text.count("\n", b.char_start, b.char_end)
    if not doc.blocks:
        raise ParseError("Empty file")
    return doc
