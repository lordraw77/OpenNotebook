"""Images and scanned PDF pages: normalization (Pillow) and transcription / description by external models.

No model runs locally: OCR goes to the `ocr` chain (e.g. Mistral OCR) or, without one, to a vision model
prompted to transcribe; the description comes from the `vision` chain.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import uuid
from dataclasses import dataclass, field

from opennotebook.config import get_settings
from opennotebook.ingestion.document import (
    DocumentBuilder,
    EmbeddedImage,
    OcrLine,
    ParsedDocument,
    group_ocr_lines,
)
from opennotebook.ingestion.parsers import ParseError, UnsupportedContent
from opennotebook.models import ModelPhase
from opennotebook.providers.gateway import GatewayError, ModelGateway

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


def parse_layout(raw: str) -> list[OcrLine] | None:
    """The lines of a layout reply (JSON array of {text, box}); None when the reply is not usable.

    Boxes are accepted as 0..1000 or 0..1 fractions of the image, [x0, y0, x1, y1]. Items with an empty text
    are dropped; when fewer than 60% of the items have a valid box the whole reply is rejected, so a model
    that cannot locate text never produces misleading highlights.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    first, last = text.find("["), text.rfind("]")
    if first < 0 or last <= first:
        return None
    try:
        items = json.loads(text[first : last + 1])
    except ValueError:
        return None
    if not isinstance(items, list):
        return None
    lines: list[OcrLine] = []
    considered = 0
    for item in items:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        considered += 1
        box = item.get("box") or item.get("bbox") or item.get("bbox_2d") or item.get("box_2d")
        try:
            x0, y0, x1, y1 = (float(v) for v in box)  # type: ignore[union-attr]
        except (TypeError, ValueError):
            continue
        scale = 1.0 if max(x0, y0, x1, y1) <= 1.0 else 1000.0
        x0, y0, x1, y1 = (min(1.0, max(0.0, v / scale)) for v in (x0, y0, x1, y1))
        if x1 <= x0 or y1 <= y0:
            continue
        lines.append(OcrLine(str(item["text"]).strip(), x0, y0, x1, y1))
    if considered == 0:
        return [] if not items else None
    if len(lines) < math.ceil(considered * 0.6):
        return None
    return lines


@dataclass
class OcrOutcome:
    text: str  # Markdown / plain text of the whole image
    lines: list[OcrLine] | None  # boxes of the lines when the model located them
    used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def layout_wanted(gateway: ModelGateway, project_id: uuid.UUID) -> bool:
    mode = get_settings().ocr_layout
    if mode == "off" or not await gateway.has_chain(ModelPhase.vision, project_id):
        return False
    return mode == "always" or not await gateway.has_chain(ModelPhase.ocr, project_id)


async def ocr_image(
    uri: str, gateway: ModelGateway, project_id: uuid.UUID, phase: ModelPhase, locate: bool
) -> OcrOutcome:
    """Text of one image, with the box of each line when `locate` and the model delivers usable ones."""
    warnings: list[str] = []
    if locate:
        try:
            result = await gateway.transcribe_image(uri, project_id, ModelPhase.vision, layout=True)
        except GatewayError:
            result = None
        lines = parse_layout(result.value) if result is not None else None
        if result is not None and lines is not None:
            text = "\n\n".join(" ".join(ln.text for ln in g) for g in group_ocr_lines(lines))
            return OcrOutcome(text, lines, [result.used.label])
        warnings.append("The model did not locate the text lines: the text is anchored to the whole page")
    plain = await gateway.transcribe_image(uri, project_id, phase)
    return OcrOutcome(plain.value, None, [plain.used.label], warnings)


async def parse_image(
    data: bytes, title: str, gateway: ModelGateway, project_id: uuid.UUID
) -> tuple[ParsedDocument, list[str]]:
    """Returns the document (OCR text + description) and the labels of the models used."""
    jpeg, width, height, warnings = normalize_image(data)
    uri = data_uri(jpeg)
    phase = await transcription_phase(gateway, project_id)
    if phase is None:
        raise UnsupportedContent(NEEDS_MODEL)
    ocr = await ocr_image(uri, gateway, project_id, phase, await layout_wanted(gateway, project_id))
    used = list(ocr.used)
    warnings.extend(ocr.warnings)
    description = ""
    if await gateway.has_chain(ModelPhase.vision, project_id):
        described = await gateway.describe_image(uri, project_id)
        description = described.value
        used.append(described.used.label)
    else:
        warnings.append("No vision model configured: the image has no description")

    b = DocumentBuilder(title)
    b.doc.page_count = 1
    b.doc.page_sizes.append({"page": 1, "width": float(width), "height": float(height)})
    full = {"page": 1, "x0": 0, "top": 0, "x1": width, "bottom": height}
    if ocr.text.strip():
        b.heading("Text in the image", 2)
        if ocr.lines:
            for group in group_ocr_lines(ocr.lines):
                boxes = [
                    {
                        "page": 1,
                        "x0": ln.x0 * width,
                        "top": ln.y0 * height,
                        "x1": ln.x1 * width,
                        "bottom": ln.y1 * height,
                    }
                    for ln in group
                ]
                b.block(" ".join(ln.text for ln in group), "ocr", bboxes=boxes)
        else:
            for para in re.split(r"\n\s*\n", ocr.text.strip()):
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


@dataclass
class OcrPages:
    texts: dict[int, str] = field(default_factory=dict)  # page -> Markdown / text
    layouts: dict[int, list[OcrLine]] = field(default_factory=dict)  # page -> located lines
    used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def ocr_scanned_pages(
    data: bytes, pages: list[int], gateway: ModelGateway, project_id: uuid.UUID
) -> OcrPages:
    """OCR of scanned pages. No model -> no OCR, a warning."""
    settings = get_settings()
    result = OcrPages()
    phase = await transcription_phase(gateway, project_id)
    if phase is None:
        result.warnings.append("Scanned pages were not transcribed: no OCR or vision model configured")
        return result
    if len(pages) > settings.ocr_max_pages:
        result.warnings.append(
            f"Only the first {settings.ocr_max_pages} scanned pages were transcribed (OCR_MAX_PAGES)"
        )
        pages = pages[: settings.ocr_max_pages]
    locate = await layout_wanted(gateway, project_id)
    used: set[str] = set()
    unlocated = 0
    for pno, jpeg in render_pdf_pages(data, pages).items():
        normalized, *_ = normalize_image(jpeg)
        outcome = await ocr_image(data_uri(normalized), gateway, project_id, phase, locate)
        result.texts[pno] = outcome.text
        if outcome.lines:
            result.layouts[pno] = outcome.lines
        elif locate:
            unlocated += 1
        used.update(outcome.used)
    result.used = sorted(used)
    if unlocated:
        result.warnings.append(
            f"The model did not locate the text lines of {unlocated} scanned page(s): "
            "they are anchored to the whole page"
        )
    return result


# --- pictures inside PDF and DOCX -----------------------------------------------------------------------


def render_pdf_regions(data: bytes, boxes: list[dict]) -> list[bytes]:
    """JPEG crops of regions of a PDF (page points, top-left origin); each page is rendered once."""
    import pypdfium2 as pdfium

    out: dict[int, bytes] = {}
    pdf = pdfium.PdfDocument(data)
    try:
        by_page: dict[int, list[int]] = {}
        for index, box in enumerate(boxes):
            by_page.setdefault(box["page"], []).append(index)
        for pno, indexes in by_page.items():
            page = pdf[pno - 1]
            width, height = page.get_size()
            scale = min(2.0, 3000.0 / max(width, height, 1.0))
            image = page.render(scale=scale).to_pil().convert("RGB")
            for index in indexes:
                box = boxes[index]
                crop = image.crop(
                    (
                        int(box["x0"] * scale),
                        int(box["top"] * scale),
                        max(int(box["x1"] * scale), int(box["x0"] * scale) + 1),
                        max(int(box["bottom"] * scale), int(box["top"] * scale) + 1),
                    )
                )
                buf = io.BytesIO()
                crop.save(buf, format="JPEG", quality=90)
                out[index] = buf.getvalue()
            page.close()
    finally:
        pdf.close()
    return [out[i] for i in range(len(boxes)) if i in out]


@dataclass
class PictureResult:
    pictures: dict[int | str, EmbeddedImage] = field(default_factory=dict)
    used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def read_pictures(
    candidates: list[tuple[int | str, bytes]],
    gateway: ModelGateway,
    project_id: uuid.UUID,
    check_size: bool,
) -> PictureResult:
    """OCR + description of pictures found inside documents.

    `candidates` is (key, image bytes) in document order. Pictures that are too small (when `check_size`),
    repeated (same pixels, e.g. a logo on every page) or unreadable are skipped; at most EMBEDDED_IMAGES_MAX
    are read. A
    failing provider call only costs that picture (a warning), never the whole source.
    """
    settings = get_settings()
    result = PictureResult()
    phase = await transcription_phase(gateway, project_id)
    if phase is None or not candidates:
        return result
    has_vision = await gateway.has_chain(ModelPhase.vision, project_id)
    seen: set[str] = set()
    used: set[str] = set()
    failed = skipped_over_limit = 0
    for key, raw in candidates:
        try:
            jpeg, width, height, _ = normalize_image(raw)
        except (ParseError, UnsupportedContent):
            continue
        if check_size and min(width, height) < settings.embedded_image_min_px:
            continue
        digest = hashlib.sha1(jpeg).hexdigest()  # noqa: S324 - de-duplication, not security
        if digest in seen:
            continue
        seen.add(digest)
        if len(result.pictures) + failed >= settings.embedded_images_max:
            skipped_over_limit += 1
            continue
        uri = data_uri(jpeg)
        try:
            ocr = await gateway.transcribe_image(uri, project_id, phase)
            used.add(ocr.used.label)
            description = ""
            if has_vision:
                described = await gateway.describe_image(uri, project_id)
                description = described.value
                used.add(described.used.label)
        except GatewayError:
            failed += 1
            continue
        if ocr.value.strip() or description.strip():
            result.pictures[key] = EmbeddedImage(ocr=ocr.value, description=description)
    result.used = sorted(used)
    if failed:
        result.warnings.append(f"{failed} picture(s) could not be read (model error) and were left out")
    if skipped_over_limit:
        result.warnings.append(
            f"{skipped_over_limit} picture(s) were not read: limit of {settings.embedded_images_max} per "
            "source (EMBEDDED_IMAGES_MAX)"
        )
    return result
