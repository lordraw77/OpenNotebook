"""Native XLSX and PPTX import: sheet/row and slide anchors, hidden sheets, limits, no converter involved."""

from __future__ import annotations

import io

import openpyxl
import pytest
from pptx import Presentation
from pptx.util import Inches

from opennotebook.ingestion.parsers import ParseError, parse, parse_pptx, parse_xlsx, sniff


def make_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Region", "Units", "Revenue"])
    for i in range(60):
        ws.append([f"R{i}", i, i * 1.5])
    ws["D3"] = "=B2+B3"
    hidden = wb.create_sheet("Secret")
    hidden.append(["do not index"])
    hidden.sheet_state = "hidden"
    wb.create_sheet("Empty")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def make_pptx() -> bytes:
    prs = Presentation()
    first = prs.slides.add_slide(prs.slide_layouts[1])
    first.shapes.title.text = "Roadmap"
    first.placeholders[1].text = "Ship the converter\nShip the graph editor"
    first.notes_slide.notes_text_frame.text = "Mention the pilot customers"
    second = prs.slides.add_slide(prs.slide_layouts[5])
    second.shapes.title.text = "Budget"
    table = second.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    table.cell(0, 0).text = "Item"
    table.cell(0, 1).text = "Cost"
    table.cell(1, 0).text = "GPU"
    table.cell(1, 1).text = "10"
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def test_xlsx_sheets_rows_and_header_repeat():
    sniffed = sniff(make_xlsx(), "sales.xlsx")
    assert sniffed.format == "xlsx"
    doc = parse(make_xlsx(), "xlsx", "sales.xlsx")
    headings = [b.text for b in doc.blocks if b.block_type == "heading"]
    assert headings == ["Sales"]  # hidden and empty sheets are skipped
    tables = [b for b in doc.blocks if b.block_type == "table"]
    assert len(tables) == 3  # 61 rows in blocks of 25
    assert tables[0].text.startswith("Sales - rows 1-25\nRegion | Units | Revenue\nR0 | 0 | 0")
    assert tables[1].text.startswith("Sales - rows 26-50\nRegion | Units | Revenue\n")  # header repeated
    assert "do not index" not in doc.text
    assert tables[0].heading_path == ("Sales",)


def test_pptx_slides_notes_tables():
    assert sniff(make_pptx(), "deck.pptx").format == "pptx"
    doc = parse(make_pptx(), "pptx", "deck.pptx")
    assert doc.page_count == 2
    headings = [(b.text, b.page) for b in doc.blocks if b.block_type == "heading"]
    assert headings == [("Slide 1: Roadmap", 1), ("Slide 2: Budget", 2)]
    text = doc.text
    assert "Ship the graph editor" in text and "Notes: Mention the pilot customers" in text
    assert "GPU | 10" in text
    notes = next(b for b in doc.blocks if b.text.startswith("Notes:"))
    assert notes.page == 1 and notes.heading_path == ("Slide 1: Roadmap",)


def test_ooxml_zip_bomb_is_refused(monkeypatch):
    monkeypatch.setattr("opennotebook.ingestion.parsers.OOXML_MAX_UNCOMPRESSED", 10)
    with pytest.raises(ParseError):
        parse_xlsx(make_xlsx(), "x.xlsx")
    with pytest.raises(ParseError):
        parse_pptx(make_pptx(), "x.pptx")


def test_native_can_be_turned_off(monkeypatch):
    from opennotebook.config import get_settings

    monkeypatch.setenv("OFFICE_NATIVE", "false")
    monkeypatch.delenv("CONVERTER_URL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(Exception, match="converter"):
            sniff(make_xlsx(), "sales.xlsx")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
