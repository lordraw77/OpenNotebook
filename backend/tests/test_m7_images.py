"""Pictures inside PDF and DOCX, OCR text anchored to line boxes, 7z/RAR sources end to end."""

from __future__ import annotations

import io
import json
import zlib

import pytest
from sqlalchemy import select

from opennotebook.config import get_settings
from opennotebook.ingestion.document import OcrLine, group_ocr_lines
from opennotebook.ingestion.images import parse_layout
from opennotebook.ingestion.parsers import parse_pdf
from opennotebook.models import Chunk, SourceStatus
from tests.factories import make_docx, make_pdf
from tests.rar_fixture import make_rar5
from tests.test_m3 import RADIO_C, m3, make_scanned_pdf, sources_of  # noqa: F401 - m3 is a fixture
from tests.test_m7_archives import make_7z
from tests.test_sources import embed_calls, jobs, run_jobs, upload  # noqa: F401 - fixtures

# --- layout replies -------------------------------------------------------------------------------------


def test_parse_layout_accepts_fences_and_both_scales():
    raw = (
        '```json\n[{"text": "HELLO", "box": [100, 200, 500, 260]}, '
        '{"text": "World", "bbox": [0.1, 0.3, 0.4, 0.35]}]\n```'
    )
    lines = parse_layout(raw)
    assert [ln.text for ln in lines] == ["HELLO", "World"]
    assert (lines[0].x0, lines[0].y0, lines[0].x1, lines[0].y1) == (0.1, 0.2, 0.5, 0.26)
    assert (lines[1].x0, lines[1].y0) == (0.1, 0.3)


def test_parse_layout_rejects_unusable_replies():
    assert parse_layout("I can see a label.") is None
    assert parse_layout("[not json]") is None
    assert parse_layout("[]") == []  # an image without text
    assert parse_layout('[{"text": "a", "box": [10, 10, 5, 5]}]') is None  # inverted box
    assert parse_layout('[{"text": "a"}, {"text": "b", "box": [1, 2, 3, 4]}]') is None  # most lines unlocated
    mixed = (
        '[{"text": "a", "box": [1, 2, 30, 40]}, {"text": "b", "box": [1, 2, 3, 4]}, '
        '{"text": "c", "box": [9]}]'
    )
    assert [ln.text for ln in parse_layout(mixed)] == ["a", "b"]  # 2 of 3 located: kept


def test_lines_are_grouped_into_paragraphs_by_gap():
    lines = [
        OcrLine("a", 0.1, 0.10, 0.9, 0.14),
        OcrLine("b", 0.1, 0.15, 0.9, 0.19),
        OcrLine("c", 0.1, 0.40, 0.9, 0.44),
    ]
    assert [[ln.text for ln in g] for g in group_ocr_lines(lines)] == [["a", "b"], ["c"]]


def test_scanned_page_layout_becomes_line_boxes():
    lines = [OcrLine("FIRMWARE 4.2", 0.1, 0.1, 0.6, 0.15), OcrLine("Serial ABC", 0.1, 0.5, 0.5, 0.55)]
    doc = parse_pdf(make_scanned_pdf(), "scan", ocr_text={1: "x"}, ocr_layout={1: lines})
    first, second = doc.blocks
    assert first.text == "FIRMWARE 4.2" and second.text == "Serial ABC"
    box = first.bboxes[0]
    assert (
        box["page"] == 1
        and box["x0"] == pytest.approx(30.0)
        and box["top"] == pytest.approx(doc.page_sizes[0]["height"] * 0.1)
    )
    assert box["x1"] == pytest.approx(180.0)  # 0.6 of a 300 pt wide page


# --- helpers --------------------------------------------------------------------------------------------


def picture_png(seed: int = 0, size: tuple[int, int] = (200, 120)) -> bytes:
    from PIL import Image

    img = Image.new("RGB", size, "white")
    for x in range(size[0]):
        for y in range(size[1]):
            img.putpixel((x, y), ((x * 3 + seed * 40) % 256, (y * 5) % 256, (x + y + seed) % 256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def pdf_with_picture(
    png: bytes, box: tuple[int, int, int, int] = (72, 400, 272, 520), text: str = "Intro"
) -> bytes:
    """A one-page text PDF with the picture drawn in `box` (PDF user space: x0, y0, x1, y1)."""
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGB")
    raw = zlib.compress(img.tobytes())
    x0, y0, x1, y1 = box
    base = make_pdf([[(12, text)]])
    # append an incremental update: image XObject + a second content stream on the page
    objs = [
        b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 "
        b"/Filter /FlateDecode /Length %d >>\nstream\n"
        % (img.width, img.height, len(raw))
        + raw
        + b"\nendstream",
    ]
    return _append_picture(base, objs[0], f"q {x1 - x0} 0 0 {y1 - y0} {x0} {y0} cm /Im1 Do Q".encode())


def _append_picture(pdf: bytes, image_obj: bytes, draw: bytes) -> bytes:
    """Rewrites a make_pdf() file (one page) with an extra image object and drawing operator."""
    import re

    text = pdf
    count = int(re.search(rb"/Size (\d+)", text).group(1))
    image_id, content_id = count, count + 1
    page = re.search(
        rb"(\d+) 0 obj\n<< /Type /Page /Parent (\d+) 0 R /MediaBox \[0 0 612 792\] /Contents (\d+) 0 R", text
    )
    page_id, parent, first_content = (int(g) for g in page.groups())
    body = text[: text.index(b"xref\n")]
    body = body.replace(
        b"/Contents %d 0 R" % first_content, b"/Contents [%d 0 R %d 0 R]" % (first_content, content_id)
    )
    body = body.replace(b"/Font << /F1", b"/XObject << /Im1 %d 0 R >> /Font << /F1" % image_id)
    out = io.BytesIO()
    out.write(body)
    out.write(b"%d 0 obj\n" % image_id + image_obj + b"\nendobj\n")
    out.write(
        b"%d 0 obj\n<< /Length %d >>\nstream\n" % (content_id, len(draw)) + draw + b"\nendstream\nendobj\n"
    )
    catalog = int(re.search(rb"/Root (\d+) 0 R", text).group(1))
    # the xref is rebuilt from scratch by scanning the objects
    data = out.getvalue()
    offsets = {int(m.group(1)): m.start() for m in re.finditer(rb"(?m)^(\d+) 0 obj", data)}
    size = max(offsets) + 1
    xref = len(data)
    table = b"xref\n0 %d\n0000000000 65535 f \n" % size + b"".join(
        b"%010d 00000 n \n" % offsets[i] for i in range(1, size)
    )
    trailer = b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, catalog, xref)
    return data + table + trailer


# --- PDF and DOCX pictures ------------------------------------------------------------------------------


async def test_picture_in_a_pdf_is_read_and_anchored(client, admin_headers, session, m3, jobs):
    await m3.assign("vision", "pixtral-large")
    pdf = pdf_with_picture(picture_png(1))
    await upload(client, admin_headers, m3.nb["id"], [("manual.pdf", pdf)])
    assert await run_jobs(session, jobs) == [SourceStatus.ready]
    src = (await sources_of(client, admin_headers))["manual.pdf"]
    chunks = (await session.scalars(select(Chunk).where(Chunk.source_id == src["id"]))).all()
    types = {c.block_type for c in chunks}
    text = " ".join(c.text for c in chunks)
    assert (
        "Intro" in text
        and "[Image] A photo of a router label" in text
        and "[Text in image] LABEL TEXT" in text
    )
    picture = next(c for c in chunks if "[Image]" in c.text)
    box = next(b for b in picture.bboxes if b["bottom"] - b["top"] > 100)  # the chunk also holds the text
    assert picture.page_start == 1 and box["page"] == 1
    # drawn at PDF y 400..520 of 792: top-left origin -> top = 792 - 520 = 272
    assert (box["x0"], box["x1"]) == (pytest.approx(72, abs=1), pytest.approx(272, abs=1))
    assert (box["top"], box["bottom"]) == (pytest.approx(272, abs=1), pytest.approx(392, abs=1))
    assert types  # pictures are read by the vision model (OCR through it as there is no OCR chain)


async def test_pictures_are_skipped_when_disabled_or_without_models(
    client, admin_headers, session, m3, jobs, monkeypatch
):
    pdf = pdf_with_picture(picture_png(2))
    await upload(client, admin_headers, m3.nb["id"], [("a.pdf", pdf)])
    assert await run_jobs(session, jobs) == [SourceStatus.ready]  # no model configured: text only
    assert m3.fake.calls == []

    await m3.assign("vision", "pixtral-large")
    monkeypatch.setenv("EMBEDDED_IMAGES", "false")
    get_settings.cache_clear()
    try:
        src = (await sources_of(client, admin_headers))["a.pdf"]
        await client.post(f"/api/sources/{src['id']}/reindex", headers=admin_headers)
        assert await run_jobs(session, jobs) == [SourceStatus.ready]
        assert m3.fake.calls == []
    finally:
        monkeypatch.delenv("EMBEDDED_IMAGES")
        get_settings.cache_clear()


async def test_small_and_page_sized_pictures_are_ignored(client, admin_headers, session, m3, jobs):
    await m3.assign("vision", "pixtral-large")
    tiny = pdf_with_picture(
        picture_png(3, (40, 40)), box=(72, 400, 102, 430), text="Tiny"
    )  # 30 pt: decoration
    await upload(client, admin_headers, m3.nb["id"], [("tiny.pdf", tiny)])
    assert await run_jobs(session, jobs) == [SourceStatus.ready]
    assert m3.fake.calls == []


async def test_picture_in_a_docx_follows_its_paragraph(client, admin_headers, session, m3, jobs):
    import docx
    from docx.shared import Inches

    await m3.assign("vision", "pixtral-large")
    d = docx.Document(io.BytesIO(make_docx([("h1", "Setup"), ("p", "Connect the cable as shown.")])))
    d.add_picture(io.BytesIO(picture_png(4)), width=Inches(2))
    d.add_paragraph("Then power on.")
    d.add_picture(io.BytesIO(picture_png(4)), width=Inches(2))  # the same picture again: read once
    tiny = io.BytesIO()
    d.save(tiny)
    await upload(client, admin_headers, m3.nb["id"], [("setup.docx", tiny.getvalue())])
    assert await run_jobs(session, jobs) == [SourceStatus.ready]
    src = (await sources_of(client, admin_headers))["setup.docx"]
    text = (await client.get(f"/api/sources/{src['id']}/text", headers=admin_headers)).text
    order = [text.index(part) for part in ("Connect the cable", "[Image] A photo", "Then power on")]
    assert order == sorted(order)
    assert text.count("[Image]") == 1
    assert [c for c in m3.fake.calls if c.startswith("describe")] == ["describe:mistral/pixtral-large"]


async def test_picture_limit_is_reported(client, admin_headers, session, m3, jobs, monkeypatch):
    import docx
    from docx.shared import Inches

    await m3.assign("vision", "pixtral-large")
    monkeypatch.setenv("EMBEDDED_IMAGES_MAX", "2")
    get_settings.cache_clear()
    try:
        d = docx.Document()
        for seed in range(4):
            d.add_paragraph(f"Figure {seed}")
            d.add_picture(io.BytesIO(picture_png(10 + seed)), width=Inches(1))
        buf = io.BytesIO()
        d.save(buf)
        await upload(client, admin_headers, m3.nb["id"], [("figs.docx", buf.getvalue())])
        assert await run_jobs(session, jobs) == [SourceStatus.ready]
        src = (await sources_of(client, admin_headers))["figs.docx"]
        assert any("limit of 2" in w for w in src["warnings"])
        text = (await client.get(f"/api/sources/{src['id']}/text", headers=admin_headers)).text
        assert text.count("[Image]") == 2
    finally:
        get_settings.cache_clear()


# --- OCR with line boxes --------------------------------------------------------------------------------


async def test_scanned_pdf_lines_get_their_own_boxes(client, admin_headers, session, m3, jobs):
    await m3.assign("vision", "pixtral-large")
    m3.fake.layout_reply = json.dumps(
        [
            {"text": "FIRMWARE VERSION 4.2", "box": [100, 100, 600, 150]},
            {"text": "Serial ABC-123", "box": [100, 600, 500, 650]},
        ]
    )
    await upload(client, admin_headers, m3.nb["id"], [("scan.pdf", make_scanned_pdf())])
    assert await run_jobs(session, jobs) == [SourceStatus.ready]
    src = (await sources_of(client, admin_headers))["scan.pdf"]
    chunks = (await session.scalars(select(Chunk).where(Chunk.source_id == src["id"]))).all()
    [chunk] = chunks
    assert "FIRMWARE VERSION 4.2" in chunk.text and "Serial ABC-123" in chunk.text
    assert len(chunk.bboxes) == 2 and all(b["x1"] < 300 and b["bottom"] < 400 for b in chunk.bboxes)
    assert chunk.bboxes[0]["bottom"] < chunk.bboxes[1]["top"]
    assert not any("did not locate" in w for w in src["warnings"])
    assert [c for c in m3.fake.calls if c.startswith("transcribe")] == []  # one call, not two


async def test_unusable_layout_falls_back_to_the_whole_page(client, admin_headers, session, m3, jobs):
    await m3.assign("vision", "pixtral-large")
    await upload(client, admin_headers, m3.nb["id"], [("scan.pdf", make_scanned_pdf())])
    assert await run_jobs(session, jobs) == [SourceStatus.ready]
    src = (await sources_of(client, admin_headers))["scan.pdf"]
    assert any("did not locate" in w for w in src["warnings"])
    [chunk] = (await session.scalars(select(Chunk).where(Chunk.source_id == src["id"]))).all()
    assert chunk.text == "LABEL TEXT"
    assert chunk.bboxes[0]["x0"] == 0 and chunk.bboxes[0]["x1"] == 300  # the whole page


async def test_dedicated_ocr_model_keeps_whole_page_anchors(client, admin_headers, session, m3, jobs):
    await m3.assign("ocr", "mistral-ocr-latest")
    await m3.assign("vision", "pixtral-large")
    await upload(client, admin_headers, m3.nb["id"], [("scan.pdf", make_scanned_pdf())])
    assert await run_jobs(session, jobs) == [SourceStatus.ready]
    assert not any(c.startswith("layout") for c in m3.fake.calls)  # `auto`: an OCR chain is used as it is


# --- 7z and RAR sources ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name, build, fmt", [("fw.7z", make_7z, "7z"), ("fw.rar", make_rar5, "rar")])
async def test_7z_and_rar_expand_into_child_sources(
    client, admin_headers, session, m3, jobs, name, build, fmt
):
    archive = build({"src/radio.c": RADIO_C, "docs/README.md": b"# Firmware\n\nBuild with make and flash.\n"})
    [res] = await upload(client, admin_headers, m3.nb["id"], [(name, archive)])
    assert res["source"]["kind"] == "archive"
    statuses = await run_jobs(session, jobs)
    assert statuses and all(s == SourceStatus.ready for s in statuses)
    by_title = await sources_of(client, admin_headers)
    root = by_title[name]
    assert root["details"]["archive"]["format"] == fmt and root["details"]["archive"]["files"] == 2
    assert by_title["src/radio.c"]["parent_source_id"] == root["id"]
