"""Application-level encryption of secrets (provider API keys) with AES-256-GCM."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from opennotebook.config import get_settings

KEY_VERSION = 1


class SecretBox:
    def __init__(self, master_key_b64: str) -> None:
        try:
            key = base64.b64decode(master_key_b64, validate=True)
        except ValueError as exc:
            raise ValueError("APP_ENCRYPTION_KEY must be base64") from exc
        if len(key) != 32:
            raise ValueError("APP_ENCRYPTION_KEY must decode to 32 bytes")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: str, associated_data: bytes = b"opennotebook:secret") -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        return self._aead.encrypt(nonce, plaintext.encode(), associated_data), nonce

    def decrypt(
        self, ciphertext: bytes, nonce: bytes, associated_data: bytes = b"opennotebook:secret"
    ) -> str:
        return self._aead.decrypt(nonce, ciphertext, associated_data).decode()


def get_secret_box() -> SecretBox:
    return SecretBox(get_settings().app_encryption_key)


def secret_hint(value: str) -> str:
    """Last 4 characters only, for display."""
    return f"…{value[-4:]}" if len(value) >= 8 else "…"
