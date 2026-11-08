"""Images and scanned PDF pages: normalization (Pillow) and transcription / description by external models.

No model runs locally: OCR goes to the `ocr` chain (e.g. Mistral OCR) or, without one, to a vision model
prompted to transcribe; the description comes from the `vision` chain.
"""

from __future__ import annotations

import base64
import io
import re
import uuid

from opennotebook.config import get_settings
from opennotebook.ingestion.document import DocumentBuilder, ParsedDocument
from opennotebook.ingestion.parsers import ParseError, UnsupportedContent
from opennotebook.models import ModelPhase
from opennotebook.providers.gateway import ModelGateway

NEEDS_MODEL = "Images need an OCR or a vision model: assign one in Settings → Models"


def normalize_image(data: bytes) -> tuple[bytes, int, int, list[str]]:
    """First frame, RGB, longest side ≤ IMAGE_MAX_SIDE, as JPEG. Rejects decompression bombs."""
    from PIL import Image, ImageOps

    settings = get_settings()
    Image.MAX_IMAGE_PIXELS = settings.image_max_pixels
    warnings: list[str] = []
    try:
        with Image.open(io.BytesIO(data)) as img:
            frames = getattr(img, "n_frames", 1)
            if frames > 1:
                warnings.append(f"Only the first of {frames} frames/pages was processed")
            img.seek(0)
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                img = background
            else:
                img = img.convert("RGB")
            img.thumbnail((settings.image_max_side, settings.image_max_side))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=90)
            return out.getvalue(), img.width, img.height, warnings
    except Image.DecompressionBombError as exc:
        raise UnsupportedContent("Image rejected: too many pixels (possible decompression bomb)") from exc
    except (OSError, ValueError) as exc:
        raise ParseError(f"Could not read the image ({exc.__class__.__name__})") from exc


def data_uri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


async def transcription_phase(gateway: ModelGateway, project_id: uuid.UUID) -> ModelPhase | None:
    if await gateway.has_chain(ModelPhase.ocr, project_id):
        return ModelPhase.ocr
    if await gateway.has_chain(ModelPhase.vision, project_id):
        return ModelPhase.vision
    return None


async def parse_image(
    data: bytes, title: str, gateway: ModelGateway, project_id: uuid.UUID
) -> tuple[ParsedDocument, list[str]]:
    """Returns the document (OCR text + description) and the labels of the models used."""
    jpeg, width, height, warnings = normalize_image(data)
    uri = data_uri(jpeg)
    phase = await transcription_phase(gateway, project_id)
    if phase is None:
        raise UnsupportedContent(NEEDS_MODEL)
    used: list[str] = []
    ocr = await gateway.transcribe_image(uri, project_id, phase)
    used.append(ocr.used.label)
    description = ""
    if await gateway.has_chain(ModelPhase.vision, project_id):
        described = await gateway.describe_image(uri, project_id)
        description = described.value
        used.append(described.used.label)
    else:
        warnings.append("No vision model configured: the image has no description")

    b = DocumentBuilder(title)
    full = {"page": 1, "x0": 0, "top": 0, "x1": width, "bottom": height}
    if ocr.value.strip():
        b.heading("Text in the image", 2)
        for para in re.split(r"\n\s*\n", ocr.value.strip()):
            b.block(para, "ocr", bboxes=[full])
    if description.strip():
        b.heading("Image description", 2)
        b.block(description.strip(), "image_description", bboxes=[full])
    doc = b.build()
    doc.warnings.extend(warnings)
    if not doc.blocks:
        raise ParseError("No text found in the image and no description available")
    return doc, used


def render_pdf_pages(data: bytes, pages: list[int], scale: float = 2.0) -> dict[int, bytes]:
    """Scanned PDF pages rendered to JPEG (pypdfium2, a PDF rasterizer - not a model)."""
    import pypdfium2 as pdfium

    out: dict[int, bytes] = {}
    pdf = pdfium.PdfDocument(data)
    try:
        for pno in pages:
            page = pdf[pno - 1]
            image = page.render(scale=scale).to_pil()
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG", quality=90)
            out[pno] = buf.getvalue()
            page.close()
    finally:
        pdf.close()
    return out


async def ocr_scanned_pages(
    data: bytes, pages: list[int], gateway: ModelGateway, project_id: uuid.UUID
) -> tuple[dict[int, str], list[str], list[str]]:
    """OCR of scanned pages; returns (page -> text, models used, warnings). No model → no OCR, a warning."""
    settings = get_settings()
    phase = await transcription_phase(gateway, project_id)
    if phase is None:
        return {}, [], ["Scanned pages were not transcribed: no OCR or vision model configured"]
    warnings: list[str] = []
    if len(pages) > settings.ocr_max_pages:
        warnings.append(
            f"Only the first {settings.ocr_max_pages} scanned pages were transcribed (OCR_MAX_PAGES)"
        )
        pages = pages[: settings.ocr_max_pages]
    texts: dict[int, str] = {}
    used: set[str] = set()
    for pno, jpeg in render_pdf_pages(data, pages).items():
        normalized, *_ = normalize_image(jpeg)
        result = await gateway.transcribe_image(data_uri(normalized), project_id, phase)
        texts[pno] = result.value
        used.add(result.used.label)
    return texts, sorted(used), warnings
