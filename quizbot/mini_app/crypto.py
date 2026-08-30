"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_HKDF_INFO = b"quizbot-mini-app-session-key-v1"


def derive_session_key(bot_token: str, user_id: int, attempt_id: str) -> bytes:
    """HKDF-SHA256 derive a 32-byte AES key scoped to one (user, attempt)
    pair. Different attempts (even by the same user) get different keys, so
    a leaked key from one play session decrypts nothing else."""
    ikm = f"{bot_token}:{user_id}:{attempt_id}".encode()
    prk = hmac.new(b"quizbot-salt", ikm, hashlib.sha256).digest()
    okm = hmac.new(prk, _HKDF_INFO + b"\x01", hashlib.sha256).digest()
    return okm  # 32 bytes -> AES-256


def encrypt_json(payload: Any, key: bytes) -> dict[str, str]:
    """Encrypt a JSON-serializable payload with AES-256-GCM. Returns
    base64-encoded {iv, ciphertext} (ciphertext includes the GCM auth tag)."""
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ciphertext = aesgcm.encrypt(iv, plaintext, None)
    return {
        "iv": base64.b64encode(iv).decode("ascii"),
        "data": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_json(envelope: dict[str, str], key: bytes) -> Any:
    """Inverse of encrypt_json -- used server-side only for tests; the
    client does the real decryption in JS via SubtleCrypto."""
    aesgcm = AESGCM(key)
    iv = base64.b64decode(envelope["iv"])
    ciphertext = base64.b64decode(envelope["data"])
    plaintext = aesgcm.decrypt(iv, ciphertext, None)
    return json.loads(plaintext)
