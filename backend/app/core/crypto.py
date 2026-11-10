"""Field-level encryption and keyed hashing (Plan §5.12).

- `EncryptedText`: AES-256-GCM, key from FIELD_ENCRYPTION_KEY (base64, 32 bytes). Stored as
  "v1:" + base64(nonce || ciphertext+tag). Rotation: add a new version prefix and key, re-encrypt
  with a CLI command (not built yet, O25; see docs/guides/ADMIN_GUIDE.en.md §7).
- `code_digest`: HMAC-SHA256 of one-time codes / session tokens with SECRET_KEY, so a database
  leak alone does not reveal usable codes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from functools import lru_cache
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.core.logging import get_logger
from app.settings import get_settings

_PREFIX = "v1:"
log = get_logger("crypto")


class KeyConfigError(RuntimeError):
    pass


@lru_cache
def _field_key() -> bytes:
    s = get_settings()
    raw = s.field_encryption_key.get_secret_value()
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        key = b""
    if len(key) == 32:
        return key
    if s.is_production:
        raise KeyConfigError("FIELD_ENCRYPTION_KEY must be 32 random bytes, base64-encoded.")
    # Development/test only: derive a stable key so the app runs before .env is filled in.
    log.warning("field_key_derived_for_dev", reason="FIELD_ENCRYPTION_KEY missing or invalid")
    return hashlib.sha256(b"fb-dev-field-key:" + s.secret_key.get_secret_value().encode()).digest()


def encrypt_text(plain: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_field_key()).encrypt(nonce, plain.encode("utf-8"), None)
    return _PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt_text(token: str) -> str:
    if not token.startswith(_PREFIX):
        raise ValueError("unknown ciphertext version")
    blob = base64.b64decode(token[len(_PREFIX) :])
    return AESGCM(_field_key()).decrypt(blob[:12], blob[12:], None).decode("utf-8")


class EncryptedText(TypeDecorator[str]):
    """Transparent AES-GCM encryption for sensitive free-text columns."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        return None if value is None else encrypt_text(str(value))

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        return None if value is None else decrypt_text(str(value))


def code_digest(code: str) -> str:
    key = get_settings().secret_key.get_secret_value().encode()
    return hmac.new(key, code.encode("utf-8"), hashlib.sha256).hexdigest()
