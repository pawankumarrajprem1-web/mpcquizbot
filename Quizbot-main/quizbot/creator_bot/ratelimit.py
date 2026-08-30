"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import functools
import logging
from typing import Awaitable, Callable

from pyrogram.types import Message

from . import state

logger = logging.getLogger(__name__)

Handler = Callable[..., Awaitable[None]]


def ratelimit(bucket: str = "default") -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        @functools.wraps(fn)
        async def wrapper(client, message: Message, *args, **kwargs):
            user = message.from_user
            if user is None:
                return await fn(client, message, *args, **kwargs)
            wait_minutes = state.check_rate_limit(user.id, bucket)
            if wait_minutes is None:
                return await fn(client, message, *args, **kwargs)
            if wait_minutes == -1:
                return None  # already warned this window, stay silent
            try:
                await message.reply(
                    f"Rate limit hit for this command. Try again in ~{wait_minutes} min. "
                    "Use /limit to check your usage."
                )
            except Exception:
                logger.debug("Failed to send rate-limit notice", exc_info=True)
            return None

        return wrapper

    return decorator
