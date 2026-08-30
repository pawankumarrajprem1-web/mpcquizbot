"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl

from pydantic import BaseModel

# initData older than this is rejected outright, regardless of hash validity
# -- limits the window in which a captured initData string could be replayed.
MAX_INIT_DATA_AGE_SECONDS = 3600


class TelegramUser(BaseModel):
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language_code: str = ""


class VerifiedSession(BaseModel):
    user: TelegramUser
    auth_date: int


def _compute_secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def verify_init_data(init_data: str, bot_token: str) -> Optional[VerifiedSession]:
    """Verify Telegram's WebApp initData HMAC signature. Returns a
    VerifiedSession on success, or None if the signature is missing,
    invalid, or the payload is stale/malformed. Never raises on bad input --
    callers should treat None as "reject the request, no exceptions leak
    what went wrong" to avoid giving an attacker a verification oracle.
    """
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret_key = _compute_secret_key(bot_token)
        computed_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            return None

        auth_date = int(pairs.get("auth_date", "0"))
        if auth_date <= 0:
            return None
        if time.time() - auth_date > MAX_INIT_DATA_AGE_SECONDS:
            return None

        user_raw = pairs.get("user")
        if not user_raw:
            return None
        user_dict = json.loads(user_raw)
        user = TelegramUser(**user_dict)

        return VerifiedSession(user=user, auth_date=auth_date)
    except Exception:
        # Malformed initData, bad JSON, missing fields, wrong types -- all
        # collapse to "not verified" rather than a 500 or a detailed error
        # that could help an attacker iterate toward a forgery.
        return None
