"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from quizbot.database import QuizRepository, get_db
from quizbot.shared.mini_app_link import mini_app_startapp_button_pyrogram

logger = logging.getLogger(__name__)


async def inline_query_handler(c: Client, iq: InlineQuery) -> None:
    """Handle `@bot <quiz_id>` inline queries by returning a shareable quiz
    info card."""
    query = iq.query.strip()
    if not query:
        await iq.answer([], switch_pm_text="Type a quiz ID to search", switch_pm_parameter="start")
        return

    quiz = await QuizRepository(get_db()).get(query)
    if not quiz:
        await iq.answer([], switch_pm_text="No quiz found", switch_pm_parameter="start")
        return

    name = quiz.get("quiz_name", "Untitled")
    quiz_type = quiz.get("quiz_type", "free")
    question_count = len(quiz.get("questions", []))
    timer = quiz.get("timer", "N/A")
    negative = quiz.get("negative_marks", 0)
    sections = quiz.get("sections", [])
    creator_id = quiz.get("creator_id")
    try:
        creator_name = (await c.get_users(creator_id)).first_name if creator_id else "Unknown"
    except Exception:
        creator_name = "Unknown"

    text = (
        f"\U0001F4DD **{name}**\n\n"
        f"❓ **Questions:** {question_count}\n"
        f"⏱️ **Timer:** {timer}s\n"
        f"🆔 **Quiz ID:** `{query}`\n"
        f"➖ **Negative marking:** `{negative}`\n"
        f"\U0001F3F7️ **Type:** `{quiz_type}`\n"
        f"👨‍💼 **Creator:** `{creator_name}`"
    )
    if sections:
        text += "\n\n\U0001F4CA **Sections:**"
        for i, s in enumerate(sections, 1):
            qr = s.get("question_range", ["?", "?"])
            text += f"\n\n\U0001F539 Section {i}: {s['name']}\n  Questions: {qr[0]} to {qr[1]}\n  Timer: {s.get('timer', 'N/A')}s"

    me = await c.get_me()
    kb_rows = [
        [InlineKeyboardButton("\U0001F680 Start", url=f"https://t.me/{me.username}?start={query}")],
        [InlineKeyboardButton("\U0001F465 Add to Group", url=f"https://t.me/{me.username}?startgroup={query}")],
        [InlineKeyboardButton("\U0001F517 Share", switch_inline_query=query)],
    ]

    # play_btn = mini_app_startapp_button_pyrogram(me.username, query, "practice", "\U0001F3AF Play Quiz")
    # if play_btn:
    #     kb_rows.append([play_btn])

    result = InlineQueryResultArticle(
        id=query,
        title=f"\U0001F4DD Quiz: {name}",
        description=f"❓ {question_count} questions | ⏱️ Timer: {timer}s",
        input_message_content=InputTextMessageContent(text, disable_web_page_preview=True),
        reply_markup=InlineKeyboardMarkup(kb_rows),
    )
    await iq.answer([result], cache_time=0)


def register(app: Client) -> None:
    app.on_inline_query()(inline_query_handler)
