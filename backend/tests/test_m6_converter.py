# ruff: noqa: F811 - fixtures imported from other test modules are redefined as parameters
"""Office documents through the isolated converter: sniffing, PDF rendition, page anchors, fallbacks."""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest

from opennotebook.config import get_settings
from opennotebook.ingestion import convert
from opennotebook.ingestion.parsers import ParseError, UnsupportedContent, sniff
from opennotebook.ingestion.pipeline import RetryableError
from opennotebook.models import Source, SourceStatus
from tests.factories import make_docx, make_pdf
from tests.test_sources import embed_calls, jobs, node, run_jobs, setup_embedding, upload  # noqa: F401

SLIDES_PDF = make_pdf(
    [
        [(20, "Roadmap"), (11, "Quarter one delivers ingestion.")],
        [(20, "Security"), (11, "The converter is isolated.")],
    ]
)


def ooxml(marker: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(marker, "<x/>")
    return buf.getvalue()


def odf(mime: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", mime)
        z.writestr("content.xml", "<x/>")
    return buf.getvalue()


PPTX = ooxml("ppt/presentation.xml")
OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(504)


@pytest.fixture
def converter(monkeypatch):  # type: ignore[no-untyped-def]
    calls: list[str] = []
    state = {"mode": "ok"}

    async def fake_to_pdf(data: bytes, extension: str) -> bytes:
        calls.append(extension)
        if state["mode"] == "down":
            raise convert.ConverterUnavailable("converter unreachable: ConnectError")
        if state["mode"] == "fail":
            raise ParseError(f"Could not convert {extension.upper()} to PDF: conversion failed")
        return SLIDES_PDF

    monkeypatch.setattr(get_settings(), "converter_url", "http://converter:8080")
    monkeypatch.setattr(convert, "to_pdf", fake_to_pdf)
    return type("Converter", (), {"calls": calls, "state": state})


def test_sniff_office_formats(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "converter_url", None)
    with pytest.raises(UnsupportedContent, match="converter service"):
        sniff(PPTX, "deck.pptx")
    assert sniff(b"{\\rtf1 hello}", "a.rtf").format == "text"  # without the converter RTF is plain text
    assert sniff(make_docx([("p", "x")]), "a.docx").format == "docx"

    monkeypatch.setattr(get_settings(), "converter_url", "http://converter:8080")
    assert (sniff(PPTX, "deck.pptx").format, sniff(PPTX, "deck.pptx").extension) == ("office", "pptx")
    assert sniff(ooxml("xl/workbook.xml"), "b.xlsx").extension == "xlsx"
    assert sniff(odf("application/vnd.oasis.opendocument.presentation"), "c.odp").extension == "odp"
    assert sniff(odf("application/vnd.oasis.opendocument.text"), "c.odt").extension == "odt"
    assert sniff(OLE2, "old.XLS").extension == "xls"
    assert sniff(b"{\\rtf1 hello}", "a.rtf").extension == "rtf"
    with pytest.raises(UnsupportedContent, match="extension"):
        sniff(OLE2, "mystery.bin")
    with pytest.raises(UnsupportedContent, match="Unsupported office"):
        sniff(odf("application/vnd.oasis.opendocument.graphics"), "d.odg")
    # an ordinary ZIP is still an archive
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "hi")
    assert sniff(buf.getvalue(), "x.zip").format == "zip"


async def test_office_document_gets_pdf_rendition_and_pages(
    client, admin_headers, session, embed_calls, jobs, converter
) -> None:
    await setup_embedding(client, admin_headers)
    project = await node(client, admin_headers, "project", "office")
    [res] = await upload(client, admin_headers, project["id"], [("deck.pptx", PPTX)])
    assert res["error"] is None
    assert await run_jobs(session, jobs) == [SourceStatus.ready]
    assert converter.calls == ["pptx"]

    sid = res["source"]["id"]
    src = (await client.get(f"/api/sources/{sid}", headers=admin_headers)).json()
    assert src["page_count"] == 2 and src["details"]["rendition"] == "pdf"
    assert src["mime_type"].endswith("presentationml.presentation")  # the original type is kept
    chunks = (await client.get(f"/api/sources/{sid}/chunks", headers=admin_headers)).json()
    assert min(c["page_start"] for c in chunks) == 1 and max(c["page_end"] for c in chunks) == 2
    view = await client.get(f"/api/sources/{sid}/view", headers=admin_headers)
    assert view.content == SLIDES_PDF and view.headers["content-type"] == "application/pdf"
    original = await client.get(f"/api/sources/{sid}/file", headers=admin_headers)
    assert original.content == PPTX
    row = await session.get(Source, uuid.UUID(sid))
    await session.refresh(row)
    assert row.view_mime_type == "application/pdf"  # citations open the PDF viewer

    # the converter turns off: re-indexing a DOCX falls back to python-docx and drops the rendition
    docx = make_docx([("h1", "Guide"), ("p", "Hold the reset button for ten seconds.")])
    [res2] = await upload(client, admin_headers, project["id"], [("guide.docx", docx)])
    converter.state["mode"] = "fail"
    assert await run_jobs(session, jobs) == [SourceStatus.ready]
    guide = (await client.get(f"/api/sources/{res2['source']['id']}", headers=admin_headers)).json()
    assert "rendition" not in guide["details"] and guide["page_count"] is None
    assert any("without page numbers" in w for w in guide["warnings"])

    # a broken presentation fails for good; an unreachable converter is retried
    [bad] = await upload(
        client, admin_headers, project["id"], [("bad.pptx", ooxml("ppt/presentation.xml") + b"x")]
    )
    assert await run_jobs(session, jobs) == [SourceStatus.failed]
    failed = (await client.get(f"/api/sources/{bad['source']['id']}", headers=admin_headers)).json()
    assert failed["error"]["code"] == "parse_error"

    converter.state["mode"] = "down"
    await client.post(f"/api/sources/{sid}/reindex", headers=admin_headers)
    with pytest.raises(RetryableError):
        await run_jobs(session, jobs)
    await session.rollback()
    retried = (await client.get(f"/api/sources/{sid}", headers=admin_headers)).json()
    assert retried["error"]["code"] == "converter_unavailable"
