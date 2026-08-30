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
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from quizbot.database import AttemptRepository, ChatSettingsRepository, QuizRepository, get_db
from quizbot.shared.html.quiz_report import render_analysis_html

from ..telegram_utils import safe_send_message

logger = logging.getLogger(__name__)


async def _require_group_admin(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    try:
        member = await ctx.bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def html_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/html` -- toggle HTML quiz-report generation for this chat."""
    chat_id = update.message.chat_id
    try:
        if update.message.chat.type != ChatType.PRIVATE:
            uid = update.message.from_user.id
            if not await _require_group_admin(ctx, chat_id, uid):
                await safe_send_message(ctx, chat_id, "\U0001F6AB Admin only.")
                return

        repo = ChatSettingsRepository(get_db())
        enabled = await repo.toggle(chat_id, "html")
        text = "✅ HTML Reports ENABLED.\nUse /html again to disable." if enabled else "❌ HTML Reports DISABLED.\nUse /html again to enable."
        await safe_send_message(ctx, chat_id, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("html_command error: %s", e)


async def pdf_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/pdf` -- toggle PDF quiz-report generation for this chat."""
    chat_id = update.message.chat_id
    try:
        if update.message.chat.type != ChatType.PRIVATE:
            uid = update.message.from_user.id
            if not await _require_group_admin(ctx, chat_id, uid):
                await safe_send_message(ctx, chat_id, "\U0001F6AB Admin only.")
                return

        repo = ChatSettingsRepository(get_db())
        enabled = await repo.toggle(chat_id, "pdf")
        text = "✅ PDF Reports ENABLED.\nUse /pdf again to disable." if enabled else "❌ PDF Reports DISABLED.\nUse /pdf again to enable."
        await safe_send_message(ctx, chat_id, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("pdf_command error: %s", e)


async def compare_results(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`compare_{qid}_{chat_id}` callback -- DMs the requesting user an
    analysis report comparing all attempts on this quiz recorded so far."""
    try:
        query = update.callback_query
        user_id = query.from_user.id
        parts = query.data.split("_")
        qid = parts[1]

        chat_settings_repo = ChatSettingsRepository(get_db())
        settings = await chat_settings_repo.get(int(parts[2])) if len(parts) > 2 else None
        if settings is not None and not settings["html_enabled"]:
            await query.answer(text="❌ HTML reports disabled. Use /html", show_alert=True)
            return

        await query.answer(text="\U0001F4CA Generating analysis...", show_alert=True)

        quiz_repo = QuizRepository(get_db())
        quiz = await quiz_repo.get(qid)
        if not quiz:
            await safe_send_message(ctx, user_id, "❌ Quiz data not found.")
            return

        attempt_repo = AttemptRepository(get_db())
        results = await attempt_repo.list_completed(qid)
        if not results:
            await safe_send_message(ctx, user_id, "No completed attempts found for this quiz yet.")
            return

        html_bytes, filename = await render_analysis_html({**quiz, "qid": qid}, results)
        await ctx.bot.send_document(
            chat_id=user_id, document=html_bytes, filename=filename, caption="\U0001F4CA Your quiz analysis report"
        )
    except Exception as e:
        logger.error("compare_results error: %s", e, exc_info=True)


def register(application: Application) -> None:
    application.add_handler(CommandHandler("html", html_command))
    application.add_handler(CommandHandler("pdf", pdf_command))
    application.add_handler(CallbackQueryHandler(compare_results, pattern="^compare_"))
