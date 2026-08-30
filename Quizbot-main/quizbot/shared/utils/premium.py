"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

from quizbot.database import UserRepository, get_db
from quizbot.shared import config


async def is_premium_user(user_id: int) -> bool:
    """Return True if the given Telegram user currently has an active premium
    subscription. If FREE_BOT is enabled, every user is treated as premium.
    """
    if config.FREE_BOT:
        return True
    repo = UserRepository(get_db())
    return await repo.is_premium(user_id)


async def grant_premium(user_id: int, days: int | None = 30) -> None:
    """Grant premium to a user for `days` days, or permanently if days is None."""
    repo = UserRepository(get_db())
    await repo.set_premium(user_id, days)


async def revoke_premium(user_id: int) -> None:
    repo = UserRepository(get_db())
    await repo.revoke_premium(user_id)
