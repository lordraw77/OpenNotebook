"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

# Known provider key shapes plus generic bearer tokens / key query parameters.
_SECRET_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{16,}"),  # Groq
    re.compile(r"sk-or-[A-Za-z0-9-]{16,}"),  # OpenRouter
    re.compile(r"csk-[A-Za-z0-9]{16,}"),  # Cerebras
    re.compile(r"nvapi-[A-Za-z0-9_-]{16,}"),  # NVIDIA
    re.compile(r"hf_[A-Za-z0-9]{16,}"),  # Hugging Face
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),  # Google API keys
    re.compile(r"AQ\.[A-Za-z0-9_-]{16,}"),  # Google API keys (newer format)
    re.compile(r"cfut_[A-Za-z0-9_-]{16,}"),  # Cloudflare user tokens
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|key)=)[^&\s\"']{8,}"),
]


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + "[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        if record.exc_info:
            entry["exc"] = redact(self.formatException(record.exc_info))
        for key in ("request_id", "path", "status", "duration_ms", "method"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in (
        "LiteLLM",
        "litellm",
        "httpx",
        "httpcore",
        "botocore",
        "urllib3",
        "alembic.runtime.plugins",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
