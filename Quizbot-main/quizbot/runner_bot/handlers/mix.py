"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging
import random
import time

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from quizbot.database import QuizRepository, get_db
from quizbot.shared.utils import is_premium_user

from ..state import pending_quiz_settings, rate_limiter, session_mgr
from ..telegram_utils import safe_send_message
from .setup_wizard import show_correct_mark_prompt

logger = logging.getLogger(__name__)


async def mix_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch an equal share of questions from each given quiz id (min 2
    ids, 20-100 total questions) and run them as one instant quiz."""
    chat_id = update.message.chat_id
    try:
        chat_type = update.message.chat.type
        user_id = update.message.from_user.id if update.message.from_user else None

        if not await is_premium_user(user_id):
            await safe_send_message(ctx, chat_id, "Please help us to make this project more valuable by purchasing premium! Thanks")
            return
        if not await rate_limiter.check(user_id):
            await safe_send_message(ctx, chat_id, "⏱️ Too many requests. Wait a moment.")
            return

        args = ctx.args or []
        if len(args) < 3:
            await safe_send_message(
                ctx, chat_id,
                "❌ Usage: <code>/mix &lt;count&gt; &lt;quizid1&gt; &lt;quizid2&gt; ...</code>\n\n"
                "Example: <code>/mix 50 QID1 QID2 QID3</code>\n"
                "• count: 20–100 (equal questions from each ID)\n"
                "• minimum 2 quiz IDs required",
                parse_mode="HTML",
            )
            return

        if not args[0].isdigit():
            await safe_send_message(ctx, chat_id, "❌ First argument must be a number (20–100).")
            return

        n = int(args[0])
        if n < 20:
            await safe_send_message(ctx, chat_id, "❌ Minimum 20 questions.")
            return
        if n > 100:
            await safe_send_message(ctx, chat_id, "❌ Maximum 100 questions.")
            return

        qids = args[1:]
        if len(qids) < 2:
            await safe_send_message(ctx, chat_id, "❌ Provide at least 2 quiz IDs.")
            return

        if session_mgr.get(chat_id):
            await safe_send_message(ctx, chat_id, "⚠️ A quiz is already running. /stop it first.")
            return

        status = await safe_send_message(ctx, chat_id, f"⏳ Fetching {len(qids)} quizzes...")

        quiz_repo = QuizRepository(get_db())
        quizzes, failed = [], []
        for qid in qids:
            q = await quiz_repo.get(qid.strip())
            if q and q.get("questions"):
                quizzes.append(q)
            else:
                failed.append(qid)

        if failed:
            await safe_send_message(ctx, chat_id, f"⚠️ Skipped (not found): {', '.join(failed)}")
        if not quizzes:
            await safe_send_message(ctx, chat_id, "❌ None of the provided quiz IDs are valid.")
            return

        per_q = max(1, n // len(quizzes))
        remainder = n - per_q * len(quizzes)

        mixed: list[dict] = []
        names: list[str] = []
        for i, q in enumerate(quizzes):
            pool = list(q["questions"])
            random.shuffle(pool)
            quota = per_q + (1 if i < remainder else 0)
            mixed.extend(pool[:quota])
            names.append(q.get("quiz_name", q.get("qid", "?")))
        random.shuffle(mixed)

        if status:
            try:
                await status.delete()
            except Exception:
                pass

        mix_id = f"MIX_{int(time.time())}_{user_id}"
        names_str = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
        mix_quiz = {
            "question_set_id": mix_id,
            "quiz_name": f"\U0001F3B2 Mix ({len(mixed)}Q) — {names_str}",
            "questions": mixed, "timer": 30, "negative_marking": 0,
            "shuffle": False, "shuffle_options": False, "sections": [],
            "creator_id": user_id, "quiz_type": "free", "promo_message": "",
        }

        cmd_thread_id = getattr(update.message, "message_thread_id", None)
        pending_quiz_settings[chat_id] = {
            "quiz": mix_quiz, "update": update, "skip": 0,
            "protect": False, "chat_type": chat_type,
            "correct_mark": 1.0, "neg_mark": 0.0,
            "shuffle_q": False, "shuffle_o": False,
            "show_explanation": False, "timer_override": None,
            "initiator_id": user_id, "message_thread_id": cmd_thread_id,
        }
        await show_correct_mark_prompt(ctx, chat_id)
    except Exception as e:
        logger.error("mix_command error: %s", e, exc_info=True)
        await safe_send_message(ctx, chat_id, "❌ Error creating mix quiz.")


def register(application: Application) -> None:
    application.add_handler(CommandHandler("mix", mix_command))
