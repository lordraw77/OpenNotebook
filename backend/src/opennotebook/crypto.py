"""Application-level encryption of secrets (provider API keys) with AES-256-GCM."""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from opennotebook.config import get_settings

KEY_VERSION = 1


def _aead(master_key_b64: str, name: str) -> AESGCM:
    try:
        key = base64.b64decode(master_key_b64, validate=True)
    except ValueError as exc:
        raise ValueError(f"{name} must be base64") from exc
    if len(key) != 32:
        raise ValueError(f"{name} must decode to 32 bytes")
    return AESGCM(key)


class SecretBox:
    """Encrypts with the current key; decrypts with the current key, then the previous one (key rotation)."""

    def __init__(self, master_key_b64: str, previous_key_b64: str = "") -> None:
        self._aead = _aead(master_key_b64, "APP_ENCRYPTION_KEY")
        self._previous = _aead(previous_key_b64, "APP_ENCRYPTION_KEY_PREVIOUS") if previous_key_b64 else None

    def encrypt(self, plaintext: str, associated_data: bytes = b"opennotebook:secret") -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        return self._aead.encrypt(nonce, plaintext.encode(), associated_data), nonce

    def decrypt(
        self, ciphertext: bytes, nonce: bytes, associated_data: bytes = b"opennotebook:secret"
    ) -> str:
        return self.decrypt_with_key_info(ciphertext, nonce, associated_data)[0]

    def decrypt_with_key_info(
        self, ciphertext: bytes, nonce: bytes, associated_data: bytes = b"opennotebook:secret"
    ) -> tuple[str, bool]:
        """Plaintext and whether the *previous* key was needed."""
        try:
            return self._aead.decrypt(nonce, ciphertext, associated_data).decode(), False
        except InvalidTag:
            if self._previous is None:
                raise
            return self._previous.decrypt(nonce, ciphertext, associated_data).decode(), True


def get_secret_box() -> SecretBox:
    settings = get_settings()
    return SecretBox(settings.app_encryption_key, settings.app_encryption_key_previous)


def secret_hint(value: str) -> str:
    """Last 4 characters only, for display."""
    return f"…{value[-4:]}" if len(value) >= 8 else "…"
