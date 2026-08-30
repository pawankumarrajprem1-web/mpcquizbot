"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from quizbot.shared import config

logger = logging.getLogger(__name__)

_JOIN_PROMPT_PHOTO = "https://graph.org/file/d44f024a08ded19452152.jpg"


async def subscribe_gate(app: Client, m: Message) -> bool:
    """Return True (and reply with a block/prompt message) if the command
    should be BLOCKED -- i.e. the user is banned from `LOG_GROUP`, or not a
    member of `REQUIRED_SUB_CHANNEL`. Returns False if the command may
    proceed. Callers should `return` immediately when this returns True:

        if await subscribe_gate(app, m):
            return
    """
    if not config.LOG_GROUP:
        return False
    try:
        member = await app.get_chat_member(config.LOG_GROUP, m.from_user.id)
        if str(member.status) == "ChatMemberStatus.BANNED":
            await m.reply_text("\U0001F6AB Banned")
            return True
    except UserNotParticipant:
        if config.REQUIRED_SUB_CHANNEL:
            await m.reply_photo(
                _JOIN_PROMPT_PHOTO,
                caption="\U0001F4E2 Please join our channel to continue.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("\U0001F517 Join", url=f"https://t.me/{config.REQUIRED_SUB_CHANNEL}")]]
                ),
            )
            return True
        return False
    except Exception as exc:
        logger.debug("subscribe_gate check failed (allowing through): %s", exc)
        return False
    return False
