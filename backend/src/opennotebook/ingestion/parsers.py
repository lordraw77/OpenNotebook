"""Deterministic parsers (no ML models): PDF (pdfplumber), DOCX (python-docx), Markdown and plain text.

Other office formats are converted to PDF by the isolated converter service (`office` format, see convert.py).

Content type is detected from the bytes, never from the file extension alone.
"""

from __future__ import annotations

import hashlib
import io
import re
import statistics
import zipfile
from dataclasses import dataclass

from opennotebook.ingestion.document import (
    DocumentBuilder,
    EmbeddedImage,
    OcrLine,
    ParsedDocument,
    group_ocr_lines,
)


class UnsupportedContent(ValueError):
    """The file type is not supported (yet); not retryable."""


class ParseError(ValueError):
    """The file could not be parsed; not retryable."""


@dataclass(frozen=True)
class Sniffed:
    # pdf | docx | xlsx | pptx | office | markdown | text | html | code | image | zip | tar | 7z | rar
    format: str
    mime_type: str
    kind: str = "file"  # SourceKind value
    language: str | None = None
    # office formats: the extension that tells the converter which import filter to use
    extension: str | None = None


MARKDOWN_EXT = (".md", ".markdown", ".mdown", ".mkd")
HTML_EXT = (".html", ".htm", ".xhtml")
_IMAGES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)
_COMPRESSED = (
    (b"\x1f\x8b", "gz", "application/gzip"),
    (b"BZh", "bz2", "application/x-bzip2"),
    (b"\xfd7zXZ\x00", "xz", "application/x-xz"),
)


def _is_tar(head: bytes) -> bool:
    return len(head) >= 262 and head[257:262] == b"ustar"


def _decompressed_head(data: bytes, codec: str, size: int = 1024) -> bytes:
    import bz2
    import gzip
    import lzma

    stream = io.BytesIO(data)
    try:
        if codec == "gz":
            with gzip.GzipFile(fileobj=stream) as f:
                return f.read(size)
        with bz2.BZ2File(stream) if codec == "bz2" else lzma.LZMAFile(stream) as f:
            return f.read(size)
    except (OSError, EOFError, lzma.LZMAError) as exc:
        raise UnsupportedContent(f"Corrupted {codec} stream") from exc


_OPENXML = "application/vnd.openxmlformats-officedocument"
_OOXML = {
    "ppt/presentation.xml": ("pptx", f"{_OPENXML}.presentationml.presentation"),
    "xl/workbook.xml": ("xlsx", f"{_OPENXML}.spreadsheetml.sheet"),
}
_ODF = {
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.presentation": "odp",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
}
_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_LEGACY = {
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
}


def converter_enabled() -> bool:
    from opennotebook.config import get_settings

    return bool(get_settings().converter_url)


def native_office() -> bool:
    """XLSX and PPTX are read directly (sheet/row and slide anchors, no converter needed) unless disabled."""
    from opennotebook.config import get_settings

    return get_settings().office_native


def _office(extension: str, mime: str) -> Sniffed:
    if not converter_enabled():
        raise UnsupportedContent(
            f"{extension.upper()} files need the converter service (CONVERTER_URL, `converter` profile)"
        )
    return Sniffed("office", mime, extension=extension)


def sniff(data: bytes, filename: str) -> Sniffed:
    name = filename.lower()
    if data.startswith(b"%PDF-"):
        return Sniffed("pdf", "application/pdf")
    if data.startswith(b"PK\x03\x04") or data.startswith(b"PK\x05\x06"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                odf = ""
                if "mimetype" in names:
                    odf = z.read("mimetype")[:100].decode("ascii", "replace").strip()
        except (zipfile.BadZipFile, KeyError) as exc:
            raise UnsupportedContent("Corrupted ZIP container") from exc
        if "word/document.xml" in names:
            return Sniffed(
                "docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                extension="docx",
            )
        for marker, (extension, mime) in _OOXML.items():
            if marker in names:
                if native_office():
                    return Sniffed(extension, mime, extension=extension)
                return _office(extension, mime)
        if odf in _ODF:
            return _office(_ODF[odf], odf)
        if "[Content_Types].xml" in names or odf:
            raise UnsupportedContent("Unsupported office format")
        return Sniffed("zip", "application/zip", kind="archive")
    if data.startswith(_OLE2):
        for extension, mime in _LEGACY.items():
            if name.endswith(extension):
                return _office(extension[1:], mime)
        raise UnsupportedContent("Legacy Office files must have a .doc, .xls or .ppt extension")
    if data.startswith(b"{\\rtf") and converter_enabled():
        return Sniffed("office", "application/rtf", extension="rtf")
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return Sniffed("7z", "application/x-7z-compressed", kind="archive")
    if data.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
        return Sniffed("rar", "application/vnd.rar", kind="archive")
    if _is_tar(data[:512]):
        return Sniffed("tar", "application/x-tar", kind="archive")
    for magic, codec, mime in _COMPRESSED:
        if data.startswith(magic):
            if _is_tar(_decompressed_head(data, codec, 512)):
                return Sniffed("tar", mime, kind="archive")
            raise UnsupportedContent(
                "Compressed single files are not supported; upload the file itself or a TAR"
            )
    for magic, mime in _IMAGES:
        if data.startswith(magic):
            return Sniffed("image", mime, kind="image")
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return Sniffed("image", "image/webp", kind="image")
    if b"\x00" in data[:8192]:
        raise UnsupportedContent("Binary file type not supported")
    try:
        decode_text(data)
    except UnicodeDecodeError as exc:
        raise UnsupportedContent("Text files must be UTF-8 encoded") from exc
    if name.endswith(MARKDOWN_EXT):
        return Sniffed("markdown", "text/markdown")
    head = data[:512].lstrip().lower()
    if name.endswith(HTML_EXT) or head.startswith((b"<!doctype html", b"<html")):
        return Sniffed("html", "text/html")
    from opennotebook.ingestion.languages import detect_language

    language = detect_language(filename, data[:200])
    if language is not None:
        return Sniffed("code", "text/plain", kind="code", language=language)
    return Sniffed("text", "text/plain")


def decode_text(data: bytes) -> str:
    text = data.decode("utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse(
    data: bytes, fmt: str, title: str, embedded: dict[str, EmbeddedImage] | None = None
) -> ParsedDocument:
    try:
        match fmt:
            case "pdf":
                return parse_pdf(data, title)
            case "code":
                from opennotebook.ingestion.code import parse_code
                from opennotebook.ingestion.languages import detect_language

                return parse_code(decode_text(data), detect_language(title, data[:200]), title)
            case "docx":
                return parse_docx(data, title, embedded)
            case "xlsx":
                return parse_xlsx(data, title)
            case "pptx":
                return parse_pptx(data, title)
            case "markdown":
                return parse_markdown(decode_text(data), title)
            case "text":
                return parse_text(decode_text(data), title)
            case "html":
                return parse_html(decode_text(data), title)
    except (UnsupportedContent, ParseError):
        raise
    except Exception as exc:  # noqa: BLE001 - library errors on malformed input become ParseError
        raise ParseError(f"Could not parse {fmt.upper()}: {exc.__class__.__name__}") from exc
    raise UnsupportedContent(f"Unsupported format {fmt}")


# --- HTML ----------------------------------------------------------------------------------------


def parse_html(html: str, title: str) -> ParsedDocument:
    """Main content of a web page as Markdown (navigation, footers and ads removed by trafilatura)."""
    import trafilatura

    markdown = trafilatura.extract(
        html,
        output_format="markdown",
        include_tables=True,
        include_links=False,
        include_images=False,
        include_comments=False,
        with_metadata=False,
    )
    page_title = _html_title(html)
    if not page_title:
        meta = trafilatura.extract_metadata(html)
        page_title = (meta.title if meta and meta.title else "") or title
    if not markdown or not markdown.strip():
        raise ParseError("No readable text found in the page")
    return parse_markdown(markdown, page_title)


def _html_title(html: str) -> str:
    import lxml.html

    try:
        titles = lxml.html.fromstring(html).xpath("//head/title/text()")
    except (ValueError, lxml.etree.ParserError):  # type: ignore[attr-defined]
        return ""
    return " ".join(str(titles[0]).split())[:300] if titles else ""


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
    return ensure_content(b.build())


def parse_text(text: str, title: str) -> ParsedDocument:
    b = DocumentBuilder(title)
    for para in re.split(r"\n\s*\n", text):
        b.block(para.rstrip(), "paragraph")
    return ensure_content(b.build())


# --- DOCX ----------------------------------------------------------------------------------------

_HEADING_STYLE = re.compile(r"^(?:heading|titolo|überschrift|titre)\s*(\d)$", re.I)


def _item_pictures(document, item) -> list[tuple[str, bytes]]:  # type: ignore[no-untyped-def]
    """(sha1, bytes) of the pictures embedded in a paragraph or table, in document order."""
    out = []
    for rid in item._element.xpath(".//a:blip/@r:embed"):
        try:
            blob = document.part.related_parts[rid].blob
        except KeyError:  # linked (external) picture: nothing inside the package
            continue
        out.append((hashlib.sha1(blob).hexdigest(), blob))  # noqa: S324 - identifier, not security
    return out


def docx_pictures(data: bytes) -> list[tuple[str, bytes]]:
    """Distinct pictures of a DOCX in document order (one used several times, e.g. a logo, appears once)."""
    import docx

    document = docx.Document(io.BytesIO(data))
    seen: set[str] = set()
    out = []
    for item in document.iter_inner_content():
        for key, blob in _item_pictures(document, item):
            if key not in seen:
                seen.add(key)
                out.append((key, blob))
    return out


def parse_docx(data: bytes, title: str, embedded: dict[str, EmbeddedImage] | None = None) -> ParsedDocument:
    """`embedded` maps the SHA-1 of a picture (see `docx_pictures`) to what the models read in it; it becomes
    text blocks right after the paragraph that contains the picture."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(io.BytesIO(data))
    b = DocumentBuilder(document.core_properties.title or title)
    list_buffer: list[str] = []
    placed: set[str] = set()

    def flush_list() -> None:
        if list_buffer:
            b.block("\n".join(list_buffer), "list")
            list_buffer.clear()

    def handle(item) -> None:  # type: ignore[no-untyped-def]
        if isinstance(item, Table):
            flush_list()
            rows = []
            for row in item.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                rows.append(" | ".join(cells))
            b.block("\n".join(rows), "table")
            return
        if not isinstance(item, Paragraph):
            return
        text = item.text.strip()
        if not text:
            flush_list()
            return
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

    for item in document.iter_inner_content():
        handle(item)
        if embedded:
            for key, _ in _item_pictures(document, item):
                if key in embedded and key not in placed:
                    placed.add(key)
                    flush_list()
                    _picture_blocks(b, embedded[key])
    flush_list()
    return ensure_content(b.build())


# --- XLSX / PPTX (read directly, without the converter) -----------------------------------------

XLSX_ROWS_PER_BLOCK = 25
XLSX_MAX_CELLS = 500_000
XLSX_MAX_SHEETS = 64
OOXML_MAX_UNCOMPRESSED = 300 * 1024 * 1024


def _check_ooxml_size(data: bytes) -> None:
    """Refuse zip bombs before handing the package to a parser."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        total = sum(i.file_size for i in z.infolist())
    if total > OOXML_MAX_UNCOMPRESSED:
        raise ParseError("The document expands to more than 300 MB")


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def parse_xlsx(data: bytes, title: str) -> ParsedDocument:
    """One heading per visible sheet, then blocks of rows repeating the header row (`Sales - rows 2-26`)."""
    import openpyxl

    _check_ooxml_size(data)
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    b = DocumentBuilder(title)
    cells = 0
    sheets = [ws for ws in wb.worksheets if ws.sheet_state == "visible"]
    for ws in sheets[:XLSX_MAX_SHEETS]:
        rows: list[tuple[int, str]] = []
        for index, row in enumerate(ws.iter_rows(values_only=True), start=1):
            values = [_cell_text(v) for v in row]
            while values and not values[-1]:
                values.pop()
            if not values:
                continue
            cells += len(values)
            if cells > XLSX_MAX_CELLS:
                b.doc.warnings.append(f"Sheet '{ws.title}' truncated: more than {XLSX_MAX_CELLS} cells")
                break
            rows.append((index, " | ".join(values)))
        _sheet_blocks(b, ws.title, rows)
        if cells > XLSX_MAX_CELLS:
            break
    if len(sheets) > XLSX_MAX_SHEETS:
        b.doc.warnings.append(f"Only the first {XLSX_MAX_SHEETS} sheets were read")
    wb.close()
    return ensure_content(b.build())


def _sheet_blocks(b: DocumentBuilder, name: str, rows: list[tuple[int, str]]) -> None:
    if not rows:
        return
    b.heading(name, 1)
    header_row, header = rows[0]
    for start in range(0, len(rows), XLSX_ROWS_PER_BLOCK):
        part = rows[start : start + XLSX_ROWS_PER_BLOCK]
        lines = [text for _, text in part]
        if part[0][0] != header_row:
            lines.insert(0, header)  # every block carries the column names
        b.block(f"{name} - rows {part[0][0]}-{part[-1][0]}\n" + "\n".join(lines), "table")


def parse_pptx(data: bytes, title: str) -> ParsedDocument:
    """One heading per slide (page = slide number): text and tables in reading order, then speaker notes."""
    from pptx import Presentation

    _check_ooxml_size(data)
    prs = Presentation(io.BytesIO(data))
    b = DocumentBuilder(prs.core_properties.title or title)
    count = 0
    for number, slide in enumerate(prs.slides, start=1):
        count = number
        shapes = sorted(slide.shapes, key=lambda s: (s.top or 0, s.left or 0))
        slide_title = ""
        title_id = None
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title_id = slide.shapes.title.shape_id
            slide_title = slide.shapes.title.text_frame.text.strip().replace("\n", " ")
        b.heading(f"Slide {number}" + (f": {slide_title}" if slide_title else ""), 1, page=number)
        for shape in shapes:
            if shape.has_text_frame and shape.shape_id != title_id:
                lines = [p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip()]
                if lines:
                    b.block("\n".join(lines), "paragraph", page=number)
            elif getattr(shape, "has_table", False) and shape.has_table:
                rows = [
                    " | ".join(c.text.strip().replace("\n", " ") for c in row.cells)
                    for row in shape.table.rows
                ]
                b.block("\n".join(rows), "table", page=number)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                b.block(f"Notes: {notes}", "paragraph", page=number)
    doc = b.build()
    doc.page_count = count or None
    return ensure_content(doc)


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


def _picture_blocks(
    b: DocumentBuilder, picture: EmbeddedImage, page: int | None = None, bboxes: list[dict] | None = None
) -> None:
    """A picture read by models becomes up to two blocks (what it shows, the text in it) at its position."""
    extra: dict = {}
    if page is not None:
        extra = {"page": page, "bboxes": bboxes or []}
    if picture.description.strip():
        b.block(f"[Image] {picture.description.strip()}", "image_description", **extra)
    if picture.ocr.strip():
        b.block(f"[Text in image] {picture.ocr.strip()}", "ocr", **extra)


def _page_pictures(page, tables: list, scanned: bool, min_px: int) -> list[dict]:  # type: ignore[no-untyped-def]
    """Pictures of a text page worth reading: big enough, not a page-sized background, not repeated art."""
    if scanned:
        return []
    width, height = float(page.width), float(page.height)
    boxes = []
    for image in page.images:
        x0, top = max(0.0, float(image["x0"])), max(0.0, float(image["top"]))
        x1, bottom = min(width, float(image["x1"])), min(height, float(image["bottom"]))
        if x1 - x0 < min_px or bottom - top < min_px:
            continue
        if (x1 - x0) * (bottom - top) >= 0.9 * width * height:
            continue
        boxes.append({"page": page.page_number, "x0": x0, "top": top, "x1": x1, "bottom": bottom})
    return boxes


def parse_pdf(
    data: bytes,
    title: str,
    ocr_text: dict[int, str] | None = None,
    allow_empty: bool = False,
    ocr_layout: dict[int, list[OcrLine]] | None = None,
    embedded: dict[int, list[EmbeddedImage]] | None = None,
) -> ParsedDocument:
    """`ocr_text` maps page numbers of scanned pages to their OCR transcription (Markdown); `ocr_layout` maps
    them
    to OCR lines with their boxes (preferred: citations highlight the lines, not the whole page); `embedded`
    maps pages to the pictures read by models (each with its box in page points); `allow_empty` returns a
    document without blocks instead of failing (first pass before OCR)."""
    import pdfplumber

    from opennotebook.config import get_settings

    min_px = get_settings().embedded_image_min_px

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
                    doc.scanned_pages.append(pno)
                    ocr = (ocr_text or {}).get(pno, "").strip()
                    lines = (ocr_layout or {}).get(pno)
                    if lines:
                        w, h = float(page.width), float(page.height)
                        for group in group_ocr_lines(lines):
                            boxes = [
                                {
                                    "page": pno,
                                    "x0": ln.x0 * w,
                                    "top": ln.y0 * h,
                                    "x1": ln.x1 * w,
                                    "bottom": ln.y1 * h,
                                }
                                for ln in group
                            ]
                            b.block(" ".join(ln.text.strip() for ln in group), "ocr", page=pno, bboxes=boxes)
                    elif ocr:
                        full = {
                            "page": pno,
                            "x0": 0,
                            "top": 0,
                            "x1": float(page.width),
                            "bottom": float(page.height),
                        }
                        for para in re.split(r"\n\s*\n", ocr):
                            b.block(para.strip(), "ocr", page=pno, bboxes=[full])
                    else:
                        empty_pages.append(pno)
                continue

            doc.image_boxes.extend(_page_pictures(page, tables, False, min_px))
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
            items += [(p.bbox["top"], "picture", p) for p in (embedded or {}).get(pno, [])]
            for _, kind, obj in sorted(items, key=lambda i: i[0]):
                if kind == "picture":
                    box = obj.bbox  # type: ignore[attr-defined]
                    _picture_blocks(b, obj, pno, [box])  # type: ignore[arg-type]
                    continue
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
                f"{len(empty_pages)} page(s) without a text layer ({_ranges(empty_pages)}) "
                "were not transcribed"
            )
        ocr_pages = sorted(set(doc.scanned_pages) - set(empty_pages))
        if ocr_pages:
            doc.warnings.append(f"Text of page(s) {_ranges(ocr_pages)} obtained by OCR")
    return b.build() if allow_empty else ensure_content(b.build())


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


def ensure_content(doc: ParsedDocument) -> ParsedDocument:
    if not doc.blocks:
        hint = f" ({'; '.join(doc.warnings)})" if doc.warnings else ""
        raise ParseError(f"No extractable text{hint}")
    return doc
