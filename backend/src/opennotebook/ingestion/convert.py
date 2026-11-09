"""Client of the isolated converter service (headless LibreOffice): office documents to PDF.

The converter runs in its own container on a network without internet access, reachable only by the worker,
so a document that exploits LibreOffice cannot reach the databases, the storage, the providers or the
internet (T5).
"""

from __future__ import annotations

import httpx

from opennotebook.config import get_settings
from opennotebook.ingestion.parsers import ParseError


class ConverterUnavailable(RuntimeError):
    """The converter could not be reached or is overloaded; the job is retried."""


async def to_pdf(data: bytes, extension: str) -> bytes:
    settings = get_settings()
    if not settings.converter_url:
        raise ConverterUnavailable("CONVERTER_URL is not set")
    url = settings.converter_url.rstrip("/") + "/convert"
    try:
        async with httpx.AsyncClient(timeout=settings.converter_timeout_seconds + 30) as client:
            response = await client.post(
                url,
                params={"ext": extension},
                content=data,
                headers={"Content-Type": "application/octet-stream"},
            )
    except httpx.HTTPError as exc:
        raise ConverterUnavailable(f"converter unreachable: {exc.__class__.__name__}") from exc
    if response.status_code in (502, 503):
        raise ConverterUnavailable(f"converter busy (HTTP {response.status_code})")
    if response.status_code != 200:
        try:
            detail = str(response.json().get("detail", ""))[:200]
        except ValueError:
            detail = ""
        raise ParseError(f"Could not convert {extension.upper()} to PDF: {detail or response.status_code}")
    pdf = response.content
    if not pdf.startswith(b"%PDF-"):
        raise ParseError(f"Could not convert {extension.upper()} to PDF: invalid output")
    return pdf
