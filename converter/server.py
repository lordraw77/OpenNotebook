"""OpenNotebook document converter: office documents to PDF with headless LibreOffice.

Runs in its own container on a network without internet access, reachable only by the worker (threat T5:
LibreOffice parses untrusted documents, so a compromise cannot reach the databases, the storage or the internet).

    POST /convert?ext=docx   body: the document  ->  200 application/pdf
    GET  /health

Every conversion runs in a fresh temporary directory with its own LibreOffice profile, with a timeout that
kills the whole process group. Macros are never executed (LibreOffice default macro security; nothing is trusted).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Formats accepted for conversion (the extension tells LibreOffice which filter to use).
EXTENSIONS = frozenset(
    {"doc", "docx", "odt", "rtf", "ppt", "pptx", "odp", "xls", "xlsx", "ods"}
)
MAX_BYTES = int(os.environ.get("CONVERTER_MAX_MB", "100")) * 1024 * 1024
TIMEOUT = float(os.environ.get("CONVERTER_TIMEOUT_SECONDS", "120"))
SLOTS = threading.BoundedSemaphore(int(os.environ.get("CONVERTER_CONCURRENCY", "2")))
SOFFICE = os.environ.get("SOFFICE", "soffice")

log = logging.getLogger("converter")


class ConversionError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def convert(data: bytes, ext: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="convert-") as tmp:
        work = Path(tmp)
        source = work / f"document.{ext}"
        source.write_bytes(data)
        out = work / "out"
        out.mkdir()
        command = [
            SOFFICE,
            f"-env:UserInstallation=file://{work / 'profile'}",
            "--headless",
            "--invisible",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out),
            str(source),
        ]
        process = subprocess.Popen(  # noqa: S603 - fixed command, the document is a file argument
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env={"HOME": str(work), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"},
        )
        try:
            _, stderr = process.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise ConversionError(504, f"conversion timed out after {TIMEOUT:.0f} s") from None
        finally:
            # LibreOffice may leave helper processes behind: the session is ours alone.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        pdf = out / "document.pdf"
        if process.returncode != 0 or not pdf.exists():
            detail = stderr.decode(errors="replace").strip().splitlines()[-1:] or ["no output"]
            raise ConversionError(422, f"conversion failed: {detail[0][:200]}")
        return pdf.read_bytes()


class Handler(BaseHTTPRequestHandler):
    server_version = "opennotebook-converter"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        log.info("%s %s", self.address_string(), format % args)

    def _reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._reply(status, json.dumps({"detail": message}).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if urlparse(self.path).path == "/health":
            self._reply(200, b'{"status":"ok"}', "application/json")
        else:
            self._error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        url = urlparse(self.path)
        if url.path != "/convert":
            self._error(404, "not found")
            return
        ext = (parse_qs(url.query).get("ext") or [""])[0].lower()
        if ext not in EXTENSIONS:
            self._error(415, f"unsupported extension {ext!r}")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._error(411, "Content-Length required")
            return
        if length <= 0 or length > MAX_BYTES:
            self._error(413, f"document must be 1 byte to {MAX_BYTES // (1024 * 1024)} MB")
            return
        data = self.rfile.read(length)
        if not SLOTS.acquire(timeout=TIMEOUT):
            self._error(503, "converter busy")
            return
        try:
            pdf = convert(data, ext)
        except ConversionError as exc:
            self._error(exc.status, str(exc))
            return
        except Exception:  # noqa: BLE001 - never leak internals to the caller
            log.exception("conversion crashed")
            self._error(500, "conversion crashed")
            return
        finally:
            SLOTS.release()
        self._reply(200, pdf, "application/pdf")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if shutil.which(SOFFICE) is None:
        sys.exit(f"{SOFFICE} not found")
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)  # noqa: S104 - container port, internal network
    log.info("converter listening on %s", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
