"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quizbot.shared.utils import grant_premium

IST_OFFSET = timedelta(hours=5, minutes=30)


async def grant_and_notify(user_id: int, days: int) -> str:
    """Grant `days` of premium to `user_id` and return the expiry timestamp
    formatted for display, e.g. '22-Aug-2026 06:30 PM'."""
    await grant_premium(user_id, days)
    expiry_utc = datetime.now(timezone.utc) + timedelta(days=days)
    expiry_ist = expiry_utc + IST_OFFSET
    return expiry_ist.strftime("%d-%b-%Y %I:%M %p")
