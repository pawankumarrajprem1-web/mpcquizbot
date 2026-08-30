"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from quizbot.database import AuthChatRepository, get_db
from quizbot.shared import config
from quizbot.shared.utils import is_premium_user, revoke_premium

from ..premium_grant import grant_and_notify
from ..ratelimit import ratelimit
from ..subscribe_gate import subscribe_gate

logger = logging.getLogger(__name__)

_UNIT_TO_DAYS = {
    "min": 1 / 1440,
    "hours": 1 / 24,
    "days": 1,
    "weeks": 7,
    "month": 30,
    "year": 365,
    "decades": 3650,
}


@ratelimit("default")
async def add_auth_cmd(c: Client, m: Message) -> None:
    """/add <chat_id> -- authorize a chat/user to access this creator's
    paid quizzes."""
    if await subscribe_gate(c, m):
        return
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("Purchase premium: /pay")
        return
    args = m.text.split()
    if len(args) != 2:
        await m.reply("Usage: `/add <chat_id>`")
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await m.reply("Usage: `/add <chat_id>`")
        return
    repo = AuthChatRepository(get_db())
    await repo.add(uid, target_id)
    await m.reply(f"Chat `{target_id}` authorized.")


@ratelimit("default")
async def rem_auth_cmd(c: Client, m: Message) -> None:
    """/rem <chat_id> -- remove a chat's access to this creator's paid
    quizzes."""
    args = m.text.split()
    if len(args) != 2:
        await m.reply("Usage: `/rem <chat_id>`")
        return
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("Purchase premium: /pay")
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await m.reply("Usage: `/rem <chat_id>`")
        return
    repo = AuthChatRepository(get_db())
    await repo.remove(uid, target_id)
    await m.reply(f"Chat `{target_id}` removed.")


@ratelimit("default")
async def remall_auth_cmd(c: Client, m: Message) -> None:
    """/remall -- clear every authorized chat for this creator's paid
    quizzes."""
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("Purchase premium: /pay")
        return
    await AuthChatRepository(get_db()).clear(uid)
    await m.reply("All auth chats removed.")


@ratelimit("default")
async def auth_cmd(c: Client, m: Message) -> None:
    """/auth <user_id> <duration> <unit> -- (owner only) manually grant
    premium, e.g. `/auth 123456 1 month`."""
    uid = m.from_user.id
    if uid != config.OWNER_ID and uid not in config.ADMIN_IDS:
        await m.reply("Owner only.")
        return
    parts = m.text.strip().split()
    if len(parts) != 4:
        await m.reply("Format: `/auth user_id duration unit`\nExample: `/auth 123456 1 month`")
        return
    try:
        target_uid = int(parts[1])
        duration_value = int(parts[2])
        unit = parts[3].lower()
        if unit not in _UNIT_TO_DAYS:
            await m.reply("Invalid unit. Use: min/hours/days/weeks/month/year/decades")
            return
        days = max(1, int(duration_value * _UNIT_TO_DAYS[unit]))
        fmt = await grant_and_notify(target_uid, days)
        await m.reply(f"User {target_uid} granted premium.\nExpiry: {fmt} IST")
        try:
            await c.send_message(target_uid, f"Premium activated!\nExpiry: {fmt} IST")
        except Exception:
            logger.debug("Could not notify user %s of premium grant", target_uid)
    except Exception as exc:
        logger.exception("auth_cmd failed")
        await m.reply(f"Error: {exc}")


@ratelimit("default")
async def removeuser_cmd(c: Client, m: Message) -> None:
    """/removeuser <user_id> -- (owner only) revoke a user's premium."""
    uid = m.from_user.id
    if uid != config.OWNER_ID and uid not in config.ADMIN_IDS:
        await m.reply("Owner only.")
        return
    parts = m.text.strip().split()
    if len(parts) != 2:
        await m.reply("Format: `/removeuser <user_id>`")
        return
    try:
        target_uid = int(parts[1])
    except ValueError:
        await m.reply("Invalid user_id.")
        return
    await revoke_premium(target_uid)
    try:
        await c.send_message(target_uid, "Your premium has been revoked.")
    except Exception:
        logger.debug("Could not notify user %s of premium revocation", target_uid)
    await m.reply(f"Premium removed for `{target_uid}`.")


def register(app: Client) -> None:
    app.on_message(filters.command("add") & filters.private)(add_auth_cmd)
    app.on_message(filters.command("rem") & filters.private)(rem_auth_cmd)
    app.on_message(filters.command("remall") & filters.private)(remall_auth_cmd)
    app.on_message(filters.command("auth") & filters.private)(auth_cmd)
    app.on_message(filters.command("removeuser") & filters.private)(removeuser_cmd)
