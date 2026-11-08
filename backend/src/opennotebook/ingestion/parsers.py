"""Deterministic parsers (no ML models): PDF (pdfplumber), DOCX (python-docx), Markdown and plain text.

Content type is detected from the bytes, never from the file extension alone.
"""

from __future__ import annotations

import io
import re
import statistics
import zipfile
from dataclasses import dataclass

from opennotebook.ingestion.document import DocumentBuilder, ParsedDocument


class UnsupportedContent(ValueError):
    """The file type is not supported (yet); not retryable."""


class ParseError(ValueError):
    """The file could not be parsed; not retryable."""


@dataclass(frozen=True)
class Sniffed:
    format: str  # pdf | docx | markdown | text
    mime_type: str


MARKDOWN_EXT = (".md", ".markdown", ".mdown", ".mkd")


def sniff(data: bytes, filename: str) -> Sniffed:
    name = filename.lower()
    if data.startswith(b"%PDF-"):
        return Sniffed("pdf", "application/pdf")
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile as exc:
            raise UnsupportedContent("Corrupted ZIP container") from exc
        if "word/document.xml" in names:
            return Sniffed("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        raise UnsupportedContent("Archives and other Office formats are supported from milestone M3")
    for magic, kind in ((b"\x89PNG", "PNG"), (b"\xff\xd8\xff", "JPEG"), (b"GIF8", "GIF"), (b"RIFF", "RIFF")):
        if data.startswith(magic):
            raise UnsupportedContent(f"{kind} images are supported from milestone M3 (OCR and description)")
    if b"\x00" in data[:8192]:
        raise UnsupportedContent("Binary file type not supported")
    try:
        decode_text(data)
    except UnicodeDecodeError as exc:
        raise UnsupportedContent("Text files must be UTF-8 encoded") from exc
    if name.endswith(MARKDOWN_EXT):
        return Sniffed("markdown", "text/markdown")
    return Sniffed("text", "text/plain")


def decode_text(data: bytes) -> str:
    text = data.decode("utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse(data: bytes, fmt: str, title: str) -> ParsedDocument:
    try:
        match fmt:
            case "pdf":
                return parse_pdf(data, title)
            case "docx":
                return parse_docx(data, title)
            case "markdown":
                return parse_markdown(decode_text(data), title)
            case "text":
                return parse_text(decode_text(data), title)
    except (UnsupportedContent, ParseError):
        raise
    except Exception as exc:  # noqa: BLE001 - library errors on malformed input become ParseError
        raise ParseError(f"Could not parse {fmt.upper()}: {exc.__class__.__name__}") from exc
    raise UnsupportedContent(f"Unsupported format {fmt}")


# --- Markdown / text -----------------------------------------------------------------------------

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^(```|~~~)")
_LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s+")


def parse_markdown(text: str, title: str) -> ParsedDocument:
    b = DocumentBuilder(title)
    para: list[str] = []
    code: list[str] | None = None

    def flush() -> None:
        if para:
            joined = "\n".join(para)
            kind = "list" if all(_LIST_ITEM.match(line) for line in para if line.strip()) else "paragraph"
            b.block(joined, kind)
            para.clear()

    for line in text.split("\n"):
        if code is not None:
            if _FENCE.match(line.strip()):
                b.block("\n".join(code), "code")
                code = None
            else:
                code.append(line)
            continue
        if _FENCE.match(line.strip()):
            flush()
            code = []
            continue
        m = _MD_HEADING.match(line)
        if m:
            flush()
            b.heading(m.group(2), len(m.group(1)))
        elif not line.strip():
            flush()
        else:
            para.append(line.rstrip())
    if code is not None:
        b.block("\n".join(code), "code")
    flush()
    return _ensure_content(b.build())


def parse_text(text: str, title: str) -> ParsedDocument:
    b = DocumentBuilder(title)
    for para in re.split(r"\n\s*\n", text):
        b.block(para.rstrip(), "paragraph")
    return _ensure_content(b.build())


# --- DOCX ----------------------------------------------------------------------------------------

_HEADING_STYLE = re.compile(r"^(?:heading|titolo|überschrift|titre)\s*(\d)$", re.I)


def parse_docx(data: bytes, title: str) -> ParsedDocument:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(io.BytesIO(data))
    b = DocumentBuilder(document.core_properties.title or title)
    list_buffer: list[str] = []

    def flush_list() -> None:
        if list_buffer:
            b.block("\n".join(list_buffer), "list")
            list_buffer.clear()

    for item in document.iter_inner_content():
        if isinstance(item, Table):
            flush_list()
            rows = []
            for row in item.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                rows.append(" | ".join(cells))
            b.block("\n".join(rows), "table")
            continue
        if not isinstance(item, Paragraph):
            continue
        text = item.text.strip()
        if not text:
            flush_list()
            continue
        style = (item.style.name if item.style is not None else "") or ""
        m = _HEADING_STYLE.match(style)
        if style.lower() == "title":
            flush_list()
            b.heading(text, 1)
        elif m:
            flush_list()
            b.heading(text, min(6, int(m.group(1)) + 1))
        elif "list" in style.lower():
            list_buffer.append(f"- {text}")
        else:
            flush_list()
            b.block(text, "paragraph")
    flush_list()
    return _ensure_content(b.build())


# --- PDF -----------------------------------------------------------------------------------------


@dataclass
class _Line:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size: float


def _lines_from_words(words: list[dict]) -> list[_Line]:
    lines: list[_Line] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        size = float(w.get("size") or (w["bottom"] - w["top"]))
        if lines and abs(w["top"] - lines[-1].top) <= max(2.0, size * 0.4) and w["x0"] >= lines[-1].x0:
            cur = lines[-1]
            cur.text += " " + w["text"]
            cur.x1 = max(cur.x1, w["x1"])
            cur.bottom = max(cur.bottom, w["bottom"])
            cur.size = max(cur.size, size)
        else:
            lines.append(_Line(w["text"], w["x0"], w["top"], w["x1"], w["bottom"], size))
    return lines


def _join_lines(lines: list[_Line]) -> str:
    out = ""
    for line in lines:
        if out.endswith("-") and line.text[:1].islower():
            out = out[:-1] + line.text  # de-hyphenate
        elif out:
            out += " " + line.text
        else:
            out = line.text
    return out


def _bbox(page: int, lines: list[_Line]) -> dict:
    return {
        "page": page,
        "x0": round(min(line.x0 for line in lines), 2),
        "top": round(min(line.top for line in lines), 2),
        "x1": round(max(line.x1 for line in lines), 2),
        "bottom": round(max(line.bottom for line in lines), 2),
    }


def _inside(word: dict, box: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = box
    cx, cy = (word["x0"] + word["x1"]) / 2, (word["top"] + word["bottom"]) / 2
    return x0 <= cx <= x1 and top <= cy <= bottom


def parse_pdf(data: bytes, title: str) -> ParsedDocument:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        meta_title = (pdf.metadata or {}).get("Title")
        b = DocumentBuilder(meta_title if isinstance(meta_title, str) and meta_title.strip() else title)
        doc = b.doc
        doc.page_count = len(pdf.pages)
        pages_words = []
        all_sizes: list[float] = []
        for page in pdf.pages:
            doc.page_sizes.append(
                {"page": page.page_number, "width": float(page.width), "height": float(page.height)}
            )
            words = page.extract_words(keep_blank_chars=False, use_text_flow=True, extra_attrs=["size"])
            pages_words.append((page, words))
            all_sizes.extend(float(w["size"]) for w in words if w.get("size"))

        body_size = statistics.median(all_sizes) if all_sizes else 10.0
        empty_pages = []
        for page, words in pages_words:
            pno = page.page_number
            tables = []
            try:
                tables = page.find_tables()
            except Exception:  # noqa: BLE001,S110 - table detection is best effort
                pass
            table_boxes = [t.bbox for t in tables]
            words = [w for w in words if not any(_inside(w, box) for box in table_boxes)]
            if not words and not tables:
                if page.images:
                    empty_pages.append(pno)
                continue

            lines = _lines_from_words(words)
            # Group lines into paragraphs: break on large vertical gaps or font size changes.
            groups: list[list[_Line]] = []
            for line in lines:
                if groups:
                    prev = groups[-1][-1]
                    gap = line.top - prev.bottom
                    if gap <= max(prev.size, line.size) * 0.8 and abs(line.size - prev.size) < 1.0:
                        groups[-1].append(line)
                        continue
                groups.append([line])

            items: list[tuple[float, str, object]] = [(g[0].top, "text", g) for g in groups]
            items += [(t.bbox[1], "table", t) for t in tables]
            for _, kind, obj in sorted(items, key=lambda i: i[0]):
                if kind == "table":
                    rows = obj.extract() or []  # type: ignore[attr-defined]
                    text = "\n".join(" | ".join((c or "").replace("\n", " ") for c in row) for row in rows)
                    x0, top, x1, bottom = obj.bbox  # type: ignore[attr-defined]
                    box = {"page": pno, "x0": x0, "top": top, "x1": x1, "bottom": bottom}
                    b.block(text, "table", page=pno, bboxes=[box])
                    continue
                group: list[_Line] = obj  # type: ignore[assignment]
                text = _join_lines(group)
                size = max(line.size for line in group)
                is_heading = size >= body_size * 1.2 and len(text) <= 150 and len(group) <= 3
                if is_heading:
                    level = 1 if size >= body_size * 1.8 else 2 if size >= body_size * 1.45 else 3
                    b.heading(text, level, page=pno, bboxes=[_bbox(pno, group)])
                else:
                    b.block(text, "paragraph", page=pno, bboxes=[_bbox(pno, group)])

        if empty_pages:
            doc.warnings.append(
                f"{len(empty_pages)} page(s) without a text layer ({_ranges(empty_pages)}); "
                "OCR of scanned pages arrives in milestone M3"
            )
    return _ensure_content(b.build())


def _ranges(pages: list[int]) -> str:
    out, start, prev = [], pages[0], pages[0]
    for p in pages[1:] + [None]:  # type: ignore[list-item]
        if p is not None and p == prev + 1:
            prev = p
            continue
        out.append(f"{start}" if start == prev else f"{start}-{prev}")
        if p is not None:
            start = prev = p
    return ", ".join(out)


def _ensure_content(doc: ParsedDocument) -> ParsedDocument:
    if not doc.blocks:
        hint = f" ({'; '.join(doc.warnings)})" if doc.warnings else ""
        raise ParseError(f"No extractable text{hint}")
    return doc
