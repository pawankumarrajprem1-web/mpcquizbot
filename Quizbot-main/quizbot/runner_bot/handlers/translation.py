"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from ..state import translation_mgr
from ..telegram_utils import safe_send_message

logger = logging.getLogger(__name__)

SUPPORTED_LANGS = {
    "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French",
    "de": "German", "it": "Italian", "pt": "Portuguese", "ru": "Russian",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "ar": "Arabic",
    "bn": "Bengali", "te": "Telugu", "ta": "Tamil", "mr": "Marathi",
    "gu": "Gujarati", "pa": "Punjabi", "ur": "Urdu",
}


async def trans_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/trans` (no args) shows current status/usage; `/trans <code>` turns
    translation on for that language; running it again with the same
    effective toggle turns translation back off."""
    chat_id = update.message.chat_id
    try:
        if update.message.chat.type != ChatType.PRIVATE:
            uid = update.message.from_user.id
            try:
                member = await ctx.bot.get_chat_member(chat_id, uid)
                if member.status not in ("administrator", "creator"):
                    await safe_send_message(ctx, chat_id, "\U0001F6AB Admin only.")
                    return
            except Exception:
                return

        if not ctx.args:
            cur = translation_mgr.get_language(chat_id)
            if cur:
                translation_mgr.set_language(chat_id, None)
                await safe_send_message(ctx, chat_id, f"❌ Translation DISABLED (was: {SUPPORTED_LANGS.get(cur, cur)})")
            else:
                codes = ", ".join(f"<code>{c}</code>" for c in ("hi", "es", "fr", "de", "bn", "te", "ta", "mr"))
                await safe_send_message(
                    ctx, chat_id, f"\U0001F310 Translation is OFF.\n\nUse <code>/trans CODE</code>\nAvailable: {codes}",
                    parse_mode=ParseMode.HTML,
                )
            return

        lang = ctx.args[0].lower()
        if lang not in SUPPORTED_LANGS:
            await safe_send_message(ctx, chat_id, f"❌ Unsupported: {lang}")
            return

        translation_mgr.set_language(chat_id, lang)
        await safe_send_message(ctx, chat_id, f"\U0001F310 Translation ON → {SUPPORTED_LANGS[lang]}")
    except Exception as e:
        logger.error("trans_command error: %s", e)


def register(application: Application) -> None:
    application.add_handler(CommandHandler("trans", trans_command))
