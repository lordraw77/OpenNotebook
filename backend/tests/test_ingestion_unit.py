"""Parsers, sniffing, chunking and sparse vectors (no services needed)."""

from __future__ import annotations

import io
import zipfile

import pytest

from opennotebook.ingestion.chunker import chunk_document, embedding_text, estimate_tokens
from opennotebook.ingestion.parsers import ParseError, UnsupportedContent, parse, sniff
from opennotebook.ingestion.sparse import document_vector, query_vector, tokenize
from tests.factories import make_docx, make_pdf

LOREM = (
    "The radio driver configures the channel before every transmission. "
    "Each channel has a frequency, a bandwidth and a transmit power. "
    "Il modulo radio verifica la potenza massima consentita dalla normativa. "
)


def test_sniff_detects_by_content_not_extension():
    assert sniff(b"%PDF-1.7 ...", "notes.txt").format == "pdf"
    assert sniff(b"# Title\nbody", "readme.md").format == "markdown"
    assert sniff(b"plain body", "file.log").format == "text"
    assert sniff(make_docx([("p", "x")]), "x.bin").format == "docx"
    assert sniff(b"\x89PNG\r\n\x1a\n....", "pic.txt").kind == "image"
    assert sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ", "x").mime_type == "image/webp"
    assert sniff(b"int main(void) { return 0; }\n", "src/main.c").language == "c"
    assert sniff(b"#!/usr/bin/env python3\nprint(1)\n", "tool").language == "python"
    assert sniff(b"<!DOCTYPE html><html><body>x</body></html>", "page").format == "html"
    assert sniff(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 20, "a.7z").kind == "archive"
    assert sniff(b"Rar!\x1a\x07\x00" + b"\x00" * 20, "a.rar").format == "rar"
    with pytest.raises(UnsupportedContent, match="Binary"):
        sniff(b"\x00\x01\x02" * 10, "blob")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.txt", "x")
    assert sniff(buf.getvalue(), "a.bin").format == "zip"
    with pytest.raises(UnsupportedContent, match="UTF-8"):
        sniff("caffè".encode("latin-1"), "x.txt")


def test_markdown_structure_and_offsets():
    md = "# Radio\n\nIntro paragraph.\n\n## Channels\n\n- one\n- two\n\n```c\nint x = 1;\n```\n\nEnd."
    doc = parse(md.encode(), "markdown", "radio.md")
    kinds = [(b.block_type, b.heading_path) for b in doc.blocks]
    assert kinds == [
        ("heading", ("Radio",)),
        ("paragraph", ("Radio",)),
        ("heading", ("Radio", "Channels")),
        ("list", ("Radio", "Channels")),
        ("code", ("Radio", "Channels")),
        ("paragraph", ("Radio", "Channels")),
    ]
    text = doc.text
    for b in doc.blocks:
        assert text[b.char_start : b.char_end] == b.text
        assert text.split("\n")[b.line_start - 1].startswith(b.text.split("\n")[0])


def test_docx_headings_lists_tables():
    data = make_docx(
        [
            ("title", "Wifi Manual"),
            ("h1", "Setup"),
            ("p", "Power on the access point."),
            ("bullet", "Connect the antenna"),
            ("bullet", "Check the LED"),
            ("h2", "Channels"),
            ("table", "Channel|Frequency;1|2412 MHz;6|2437 MHz"),
        ]
    )
    doc = parse(data, "docx", "manual.docx")
    types = [b.block_type for b in doc.blocks]
    assert types == ["heading", "heading", "paragraph", "list", "heading", "table"]
    table = doc.blocks[-1]
    assert table.heading_path == ("Wifi Manual", "Setup", "Channels")
    assert "6 | 2437 MHz" in table.text


def test_pdf_pages_headings_and_bboxes():
    data = make_pdf(
        [
            [(24, "Radio Guide"), (11, "First page body text about channels."), (11, "Second line of body.")],
            [(16, "Power"), (11, "Transmit power must stay within limits.")],
        ]
    )
    doc = parse(data, "pdf", "guide.pdf")
    assert doc.page_count == 2
    assert doc.page_sizes[0]["width"] == 612
    headings = [(b.text, b.heading_level, b.page) for b in doc.blocks if b.block_type == "heading"]
    assert headings == [("Radio Guide", 1, 1), ("Power", 2, 2)]
    body = next(b for b in doc.blocks if "Transmit power" in b.text)
    assert body.page == 2 and body.heading_path == ("Radio Guide", "Power")
    box = body.bboxes[0]
    assert box["page"] == 2 and 0 < box["x0"] < box["x1"] <= 612 and box["top"] < box["bottom"]


def test_pdf_without_text_layer_fails_clearly():
    with pytest.raises(ParseError, match="No extractable text"):
        parse(make_pdf([[]]), "pdf", "scan.pdf")


@pytest.mark.parametrize(("size", "overlap"), [(40, 8), (80, 16), (512, 64)])
def test_chunk_invariants(size, overlap):
    md = "# Guide\n\n" + "\n\n".join(f"## Section {i}\n\n" + LOREM * (1 + i % 3) for i in range(8))
    doc = parse(md.encode(), "markdown", "guide.md")
    chunks = chunk_document(doc, size=size, overlap=overlap)
    text = doc.text
    assert chunks, "at least one chunk"
    covered_end = 0
    for i, c in enumerate(chunks):
        assert c.ordinal == i
        assert text[c.char_start : c.char_end] == c.text  # exact provenance
        assert c.token_count <= size * 1.2  # estimate on joined units
        assert c.heading_path[0] == "Guide"
        assert c.char_start <= covered_end or i == 0  # contiguous coverage (overlap or adjacency)
        covered_end = max(covered_end, c.char_end + 2)
    assert chunks[-1].char_end == len(text)


def test_chunk_overlap_shares_text():
    doc = parse(("Sentence number %d is here. " * 60 % tuple(range(60))).encode(), "text", "t.txt")
    chunks = chunk_document(doc, size=50, overlap=15)
    assert len(chunks) > 2
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.char_start < a.char_end, "consecutive chunks overlap"


def test_chunk_validation_and_embedding_header():
    doc = parse(b"# A\n\nbody", "markdown", "t.md")
    with pytest.raises(ValueError):
        chunk_document(doc, size=10, overlap=10)
    chunk = chunk_document(doc)[0]
    assert embedding_text("Doc", chunk).startswith("Doc > A\n\n")
    assert estimate_tokens("") == 0


def test_sparse_vectors():
    assert tokenize("Il canale e THE channel, 2.4GHz!") == ["canale", "channel", "4ghz"]
    idx, vals = document_vector("channel channel power")
    assert len(idx) == 2 and all(v > 0 for v in vals)
    weights = dict(zip(idx, vals, strict=True))
    q_idx, _ = query_vector("channel")
    assert weights[q_idx[0]] > min(vals)  # repeated term weighs more
    assert document_vector("the and of") == ([], [])
