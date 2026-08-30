"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from telegram import Poll, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from quizbot.database import AuthChatRepository, QuizRepository, get_db
from quizbot.shared.rich_quiz import RichDispatchResult, enrich_question_dispatch
from quizbot.shared.utils import is_premium_user

from ..quiz_utils import shuffle_options_multi
from ..state import channel_poll_tasks
from ..telegram_utils import (
    prepare_poll_data,
    safe_send_message,
    safe_send_poll,
    send_raw_api,
)

logger = logging.getLogger(__name__)

_ANON_ADMIN_ID = 1087968824


async def _pollquiz_send_one(
    ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, q: dict, idx: int, total: int,
    do_shuffle: bool, is_anonymous: bool = True, shuffle_count: int = 0,
) -> bool:
    """Send one question as a never-expiring poll. Returns True on success.
    Applies the same rich-text pre-pass as the timed group/private senders:
    a rich question/options/reply_text is pre-sent via sendRichMessage
    before the poll goes out (see `quizbot.shared.rich_quiz`)."""
    try:
        options = list(q["options"])
        correct_id = q["correct_option_id"]
        correct_ids = correct_id if isinstance(correct_id, list) else [correct_id]
        is_multi = len(correct_ids) > 1
        reply_text = q.get("reply_text")
        file_id = q.get("file_id")

        if do_shuffle:
            options, correct_ids = shuffle_options_multi(options, correct_ids, shuffle_count)

        rich_res: RichDispatchResult = await enrich_question_dispatch(
            lambda method, params: send_raw_api(ctx, method, params),
            lambda text: safe_send_message(ctx, chat_id, text, parse_mode=ParseMode.HTML),
            chat_id, q, idx, total,
        )
        if rich_res.rich_sent:
            await asyncio.sleep(1)

        _rt = None if rich_res.suppress_reply_text else reply_text

        if file_id:
            try:
                await ctx.bot.send_photo(chat_id=chat_id, photo=file_id)
                await asyncio.sleep(0.5)
            except Exception:
                pass

        _q_text = rich_res.poll_question_override or q["question"]
        poll_q, poll_opts, poll_expl, overflow, poll_desc = prepare_poll_data(
            _q_text, options, correct_ids[0], q.get("explanation"), _rt, idx, total
        )
        if rich_res.poll_options_override:
            poll_opts = rich_res.poll_options_override
        if rich_res.suppress_description:
            poll_desc = None
            overflow = None

        if overflow:
            await safe_send_message(ctx, chat_id, overflow, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.5)

        poll_kwargs: dict[str, Any] = {}
        if is_multi:
            poll_kwargs["correct_option_ids"] = correct_ids
            poll_kwargs["allows_multiple_answers"] = True
        else:
            poll_kwargs["correct_option_id"] = correct_ids[0]
        if poll_desc:
            poll_kwargs["description"] = poll_desc

        sent = await safe_send_poll(
            ctx, chat_id, question=poll_q, options=poll_opts, type=Poll.QUIZ,
            explanation=poll_expl, is_anonymous=is_anonymous, **poll_kwargs,
        )
        return bool(sent)
    except Exception as e:
        logger.error("_pollquiz_send_one idx=%d: %s", idx, e, exc_info=True)
        return False


async def run_channel_pollquiz(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, quiz: dict, is_anonymous: bool = True) -> None:
    """Core loop that sends every question as a poll, then a final
    self-score poll. Cancellable via `channel_poll_tasks`."""
    try:
        questions = quiz.get("questions", [])
        total = len(questions)
        do_shuffle = quiz.get("shuffle_options", False)
        shuffle_o_count = quiz.get("shuffle_options_count", 0)
        poll_delay = 3.5 if total <= 20 else 4.0 if total <= 50 else 5.0

        await safe_send_message(
            ctx, chat_id,
            f"\U0001F4E2 <b>{quiz.get('quiz_name', 'Quiz')}</b>\n"
            f"❓ {total} questions • ♾️ No timer — answer at your own pace!",
            parse_mode=ParseMode.HTML,
        )
        await asyncio.sleep(1.5)

        for idx, q in enumerate(questions):
            if asyncio.current_task().cancelled():
                raise asyncio.CancelledError()
            sent = await _pollquiz_send_one(ctx, chat_id, q, idx, total, do_shuffle, is_anonymous=is_anonymous, shuffle_count=shuffle_o_count)
            await asyncio.sleep(poll_delay if sent else poll_delay + 2.0)

        score_options = [str(i) for i in range(total + 1)]
        if len(score_options) <= 10:
            await ctx.bot.send_poll(
                chat_id=chat_id, question=f"✅ Quiz done! How many did you get correct? (out of {total})",
                options=score_options, is_anonymous=is_anonymous, allows_multiple_answers=False,
            )
        else:
            for start in range(0, len(score_options), 10):
                chunk = score_options[start:start + 10]
                label = f"{start}–{start + len(chunk) - 1}"
                await ctx.bot.send_poll(
                    chat_id=chat_id, question=f"✅ Score check ({label} correct out of {total})?",
                    options=chunk, is_anonymous=is_anonymous, allows_multiple_answers=False,
                )
                await asyncio.sleep(1)
    except asyncio.CancelledError:
        await safe_send_message(ctx, chat_id, "\U0001F6D1 Poll quiz stopped.")
    except Exception as e:
        logger.error("run_channel_pollquiz error: %s", e, exc_info=True)
    finally:
        channel_poll_tasks.pop(chat_id, None)


async def pollquiz_channel_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/pollquiz QUIZID` -- runs in a group/supergroup (or as a direct
    command in a channel that allows bot commands)."""
    chat_id = update.message.chat_id
    try:
        chat_type = update.message.chat.type
        user_id = update.message.from_user.id if update.message.from_user else None

        try:
            await ctx.bot.delete_message(chat_id, update.message.message_id)
        except Exception:
            pass

        if not ctx.args:
            await safe_send_message(ctx, chat_id, "Usage: /pollquiz QUIZID")
            return

        if user_id and user_id != _ANON_ADMIN_ID and not await is_premium_user(user_id):
            await safe_send_message(ctx, chat_id, "Please help us to make this project more valuable by purchasing premium! Thanks")
            return

        existing = channel_poll_tasks.get(chat_id)
        if existing and not existing.done():
            await safe_send_message(ctx, chat_id, "⚠️ A poll quiz is already running. Use /pollstop to stop it.")
            return

        qid = ctx.args[0]
        quiz_repo = QuizRepository(get_db())
        quiz = await quiz_repo.get(qid)
        if not quiz:
            await safe_send_message(ctx, chat_id, "❌ Invalid QuestionSetID.")
            return

        questions = quiz.get("questions", [])
        if not questions:
            await safe_send_message(ctx, chat_id, "❌ Quiz has no questions.")
            return

        is_anon = chat_type == "channel"
        task = asyncio.create_task(run_channel_pollquiz(ctx, chat_id, quiz, is_anonymous=is_anon))
        channel_poll_tasks[chat_id] = task
    except Exception as e:
        logger.error("pollquiz_channel_command error: %s", e, exc_info=True)


async def pollstop_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/pollstop` -- cancels a running `/pollquiz` in this chat."""
    chat_id = update.message.chat_id
    try:
        try:
            await ctx.bot.delete_message(chat_id, update.message.message_id)
        except Exception:
            pass

        task = channel_poll_tasks.get(chat_id)
        if task and not task.done():
            task.cancel()
        else:
            await safe_send_message(ctx, chat_id, "⚠️ No poll quiz is running.")
    except Exception as e:
        logger.error("pollstop_command error: %s", e, exc_info=True)


async def check_channel_paid_access(quiz: dict, chat_id: int) -> Optional[str]:
    """For a paid quiz posted from a channel context, return an error
    message if the channel isn't authorised, or None if allowed."""
    creator_id = quiz.get("creator_id")
    if quiz.get("quiz_type") != "paid" or not creator_id:
        return None
    auth_repo = AuthChatRepository(get_db())
    auth_users = await auth_repo.get(creator_id)
    if chat_id in auth_users:
        return None
    return f"❌ Paid quiz. Contact creator ID {creator_id} for access."


def register(application: Application) -> None:
    application.add_handler(CommandHandler("pollquiz", pollquiz_channel_command))
    application.add_handler(CommandHandler("pollstop", pollstop_command))
