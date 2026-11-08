"""Test document builders (no extra dependencies)."""

from __future__ import annotations

import io


def make_pdf(pages: list[list[tuple[float, str]]]) -> bytes:
    """Minimal text PDF: each page is a list of (font size, line); lines flow from the top."""
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []
    pages_obj_index = len(objects) + 1 + 2 * len(pages)  # reserved later
    for lines in pages:
        y = 760.0
        ops = []
        for size, text in lines:
            safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"BT /F1 {size} Tf 72 {y:.1f} Td ({safe}) Tj ET")
            y -= size * 1.6
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_obj_index, content, font)
            )
        )
    kids = b" ".join(b"%d 0 R" % i for i in page_ids)
    pages_id = add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids)))
    assert pages_id == pages_obj_index
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref)
    )
    return out.getvalue()


def make_docx(blocks: list[tuple[str, str]]) -> bytes:
    """Build a DOCX from (style, text) pairs.

    style is one of title, h1, h2, p, bullet, table; table text separates cells with | and rows with ;
    """
    import docx

    d = docx.Document()
    for style, text in blocks:
        if style == "title":
            d.add_heading(text, level=0)
        elif style.startswith("h"):
            d.add_heading(text, level=int(style[1:]))
        elif style == "bullet":
            d.add_paragraph(text, style="List Bullet")
        elif style == "table":
            rows = [r.split("|") for r in text.split(";")]
            t = d.add_table(rows=len(rows), cols=len(rows[0]))
            for i, row in enumerate(rows):
                for j, cell in enumerate(row):
                    t.cell(i, j).text = cell.strip()
        else:
            d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
