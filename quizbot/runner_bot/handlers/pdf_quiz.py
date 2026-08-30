"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from quizbot.shared import config
from quizbot.shared.utils import is_premium_user
from quizbot.shared.utils.async_files import remove_file, write_temp_file

from ..ai_providers import gemini_page_questions, get_provider_key_single
from ..state import PDF_QUIZ_SESSIONS
from ..telegram_utils import safe_send_message
from .ai_quiz import _launch_ai_quiz  # reuse the same quiz-launch path as /aiquiz

logger = logging.getLogger(__name__)


async def pdfquiz_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to a PDF with `/pdfquiz [page_range]` to start.

    Usage:
      /pdfquiz          -- asks for a page range interactively
      /pdfquiz 1-10     -- directly starts with pages 1-10
      /pdfquiz all      -- directly starts with all pages (max 20)
    """
    chat_id = update.message.chat_id
    try:
        user_id = update.message.from_user.id

        if not await is_premium_user(user_id):
            await safe_send_message(ctx, chat_id, "❌ Premium required.")
            return

        gemini_key = await get_provider_key_single(user_id, "gemini")
        if not gemini_key:
            await safe_send_message(
                ctx, chat_id,
                "\U0001F511 <b>Gemini key required for PDF quiz</b>\n\n"
                "Get a free key at <a href='https://aistudio.google.com'>aistudio.google.com</a>\n"
                "Then: <code>/setkey gemini AIzaSy...</code>",
                parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )
            return

        doc = None
        if update.message.reply_to_message:
            rd = update.message.reply_to_message.document
            if rd and rd.mime_type == "application/pdf":
                doc = rd
        if not doc:
            await safe_send_message(
                ctx, chat_id,
                "\U0001F4C4 <b>How to use /pdfquiz</b>\n\n"
                "Reply to any PDF message with:\n"
                "• <code>/pdfquiz</code> — asks page range interactively\n"
                "• <code>/pdfquiz 1-10</code> — directly use pages 1 to 10\n"
                "• <code>/pdfquiz all</code> — all pages (max 20)\n\n"
                "⚠️ Requires Gemini key: <code>/setkey gemini YOUR_KEY</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        sm = await safe_send_message(ctx, chat_id, "\U0001F4E5 Downloading PDF...")
        file = await ctx.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        pdf_path = os.path.join(config.TEMP_DIR, f"pdfquiz_{user_id}_{int(time.time())}.pdf")
        await write_temp_file(bytes(file_bytes), pdf_path)

        total_pages = await _count_pdf_pages(pdf_path)

        PDF_QUIZ_SESSIONS[user_id] = {
            "pdf_path": pdf_path, "gemini_key": gemini_key, "total_pages": total_pages,
            "step": "pages", "chat_id": chat_id, "chat_type": str(update.message.chat.type), "user_id": user_id,
        }

        page_info = f" ({total_pages} pages)" if total_pages else ""
        inline_range = " ".join(ctx.args).strip().lower() if ctx.args else ""

        if inline_range:
            try:
                start_p, end_p = _parse_range(inline_range, total_pages)
            except ValueError:
                await sm.edit_text("❌ Invalid page range. Use <code>1-10</code> or <code>all</code>", parse_mode=ParseMode.HTML)
                PDF_QUIZ_SESSIONS.pop(user_id, None)
                return
            sess = PDF_QUIZ_SESSIONS[user_id]
            sess["page_start"], sess["page_end"], sess["step"] = start_p, end_p, "count"
            await sm.edit_text(
                f"\U0001F4C4 <b>PDF ready{page_info}</b>\n\n✅ Pages <b>{start_p}–{end_p}</b> selected "
                f"({end_p - start_p + 1} page(s))\n\nHow many questions to generate?",
                parse_mode=ParseMode.HTML, reply_markup=_count_kb(user_id),
            )
            return

        await sm.edit_text(
            f"\U0001F4C4 <b>PDF ready{page_info}</b>\n\nSend page range to generate questions from:\n"
            f"• <code>1-5</code> — pages 1 to 5\n• <code>3-10</code> — pages 3 to 10\n"
            f"• <code>all</code> — all pages (max 20)\n\n"
            f"<i>Tip: you can also pass range directly: <code>/pdfquiz 1-10</code></i>\n\n"
            f"Each page is sent to Gemini vision one by one \U0001F50D",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error("pdfquiz_command error: %s", e, exc_info=True)
        try:
            await safe_send_message(ctx, chat_id, f"❌ Error: {str(e)[:200]}")
        except Exception:
            pass


def _parse_range(text: str, total_pages: int) -> tuple[int, int]:
    if text == "all":
        return 1, (min(20, total_pages) if total_pages else 20)
    rparts = text.split("-")
    start_p = int(rparts[0].strip())
    end_p = int(rparts[1].strip())
    if start_p < 1 or end_p < start_p:
        raise ValueError("bad range")
    return start_p, min(end_p, start_p + 19)  # max 20 pages


def _count_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(str(n), callback_data=f"pdfq_count_{user_id}_{n}") for n in (5, 10, 15, 20)],
        [InlineKeyboardButton(str(n), callback_data=f"pdfq_count_{user_id}_{n}") for n in (25, 30, 40, 50)],
    ])


async def _count_pdf_pages(pdf_path: str) -> int:
    """Offloads the synchronous fitz.open() call to a thread-pool executor."""
    try:
        import fitz
    except ImportError:
        return 0

    def _count() -> int:
        doc = fitz.open(pdf_path)
        try:
            return doc.page_count
        finally:
            doc.close()

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _count)


async def pdfquiz_message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle a plain-text page-range reply during the /pdfquiz setup step.
    Returns True if the message was consumed by this flow."""
    try:
        user_id = update.message.from_user.id
        chat_id = update.message.chat_id
        sess = PDF_QUIZ_SESSIONS.get(user_id)
        if not sess or sess.get("step") != "pages":
            return False

        text = update.message.text.strip().lower()
        try:
            start_p, end_p = _parse_range(text, sess.get("total_pages", 0))
        except ValueError:
            await safe_send_message(ctx, chat_id, "❌ Invalid format. Send like <code>1-10</code> or <code>all</code>", parse_mode=ParseMode.HTML)
            return True

        sess["page_start"], sess["page_end"], sess["step"] = start_p, end_p, "count"
        await safe_send_message(
            ctx, chat_id,
            f"✅ Pages <b>{start_p}–{end_p}</b> selected ({end_p - start_p + 1} page(s))\n\nHow many questions to generate?",
            parse_mode=ParseMode.HTML, reply_markup=_count_kb(user_id),
        )
        return True
    except Exception as e:
        logger.error("pdfquiz_message_handler error: %s", e, exc_info=True)
        return False


async def pdfquiz_text_gate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """MessageHandler entry point: silently ignores text outside the /pdfquiz flow."""
    await pdfquiz_message_handler(update, ctx)


async def pdfquiz_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all `pdfq_`-prefixed callbacks."""
    try:
        query = update.callback_query
        await query.answer()
        data = query.data
        parts = data.split("_", 3)
        step, uid_s = parts[1], parts[2]
        value = parts[3] if len(parts) > 3 else None
        uid = int(uid_s)

        if query.from_user.id != uid:
            await query.answer("❌ Not your session", show_alert=True)
            return

        sess = PDF_QUIZ_SESSIONS.get(uid)
        if not sess:
            await query.message.edit_text("❌ Session expired. /pdfquiz again")
            return

        msg = query.message

        if step == "count":
            sess["count"] = int(value)
            await msg.edit_text(
                f"✅ {value} questions\n\nDifficulty?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F7E1 Moderate", callback_data=f"pdfq_diff_{uid}_moderate")],
                    [InlineKeyboardButton("\U0001F534 Hard", callback_data=f"pdfq_diff_{uid}_hard")],
                    [InlineKeyboardButton("\U0001F480 Extreme Hard", callback_data=f"pdfq_diff_{uid}_extreme")],
                ]),
            )
        elif step == "diff":
            sess["diff"] = value
            await msg.edit_text(
                f"✅ {value.title()}\n\nExam style?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F4CB SSC Type", callback_data=f"pdfq_exam_{uid}_ssc")],
                    [InlineKeyboardButton("\U0001F3DB Civil Services", callback_data=f"pdfq_exam_{uid}_civil")],
                    [InlineKeyboardButton("\U0001F4DD Common One Day", callback_data=f"pdfq_exam_{uid}_oneway")],
                ]),
            )
        elif step == "exam":
            sess["exam"] = value
            await msg.edit_text(
                "✅ Exam style set\n\nLanguage?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F1EC\U0001F1E7 English", callback_data=f"pdfq_lang_{uid}_en"),
                     InlineKeyboardButton("\U0001F1EE\U0001F1F3 Hindi", callback_data=f"pdfq_lang_{uid}_hi")],
                    [InlineKeyboardButton("\U0001F500 Hinglish", callback_data=f"pdfq_lang_{uid}_hinglish")],
                ]),
            )
        elif step == "lang":
            sess["lang"] = value
            pages_count = sess["page_end"] - sess["page_start"] + 1
            await msg.edit_text(
                f"\U0001F4C4 <b>Starting page-by-page generation...</b>\n\n"
                f"\U0001F4C4 Pages: {sess['page_start']}–{sess['page_end']} ({pages_count} pages)\n"
                f"\U0001F3AF Target: {sess['count']} questions\n\U0001F50D Sending each page to Gemini vision...",
                parse_mode=ParseMode.HTML,
            )
            from ..state import tasks
            tasks.spawn(_pdfquiz_generate_flow(uid, ctx, msg, sess), name=f"pdfquiz_gen_{uid}")
        elif step == "timer":
            sess["timer"] = int(value)
            await msg.edit_text(
                f"✅ Timer: {value}s\n\n➖ Negative marking?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("None", callback_data=f"pdfq_neg_{uid}_0"),
                     InlineKeyboardButton("1/4", callback_data=f"pdfq_neg_{uid}_0.25"),
                     InlineKeyboardButton("1/3", callback_data=f"pdfq_neg_{uid}_0.333")],
                    [InlineKeyboardButton("1/2", callback_data=f"pdfq_neg_{uid}_0.5"),
                     InlineKeyboardButton("1", callback_data=f"pdfq_neg_{uid}_1.0")],
                ]),
            )
        elif step == "neg":
            sess["neg"] = float(value)
            await msg.edit_text(
                f"✅ Negative: {value}\n\n✅ Correct mark?",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(str(n), callback_data=f"pdfq_cm_{uid}_{n}") for n in (1, 2, 3, 4)]]),
            )
        elif step == "cm":
            sess["cm"] = int(value)
            await msg.edit_text(
                f"✅ Correct: +{value}\n\n\U0001F500 Shuffle?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F500 Questions", callback_data=f"pdfq_shuffle_{uid}_q"),
                     InlineKeyboardButton("\U0001F500 Options", callback_data=f"pdfq_shuffle_{uid}_o"),
                     InlineKeyboardButton("\U0001F500 Both", callback_data=f"pdfq_shuffle_{uid}_b")],
                    [InlineKeyboardButton("⏭ No Shuffle", callback_data=f"pdfq_shuffle_{uid}_none")],
                ]),
            )
        elif step == "shuffle":
            sess["shuffle_q"] = value in ("q", "b")
            sess["shuffle_o"] = value in ("o", "b")
            slbl = {"q": "Questions", "o": "Options", "b": "Both", "none": "None"}.get(value, "None")
            if sess["shuffle_o"]:
                await msg.edit_text(
                    f"✅ Shuffle: {slbl}\n\n\U0001F500 Shuffle how many options?",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("First 2", callback_data=f"pdfq_shufflecount_{uid}_2"),
                         InlineKeyboardButton("First 4", callback_data=f"pdfq_shufflecount_{uid}_4")],
                        [InlineKeyboardButton("All", callback_data=f"pdfq_shufflecount_{uid}_all")],
                    ]),
                )
            else:
                sess["shuffle_o_count"] = 0
                await msg.edit_text(
                    f"✅ Shuffle: {slbl}\n\n\U0001F4A1 Show explanation after each question?",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Yes", callback_data=f"pdfq_ex_{uid}_yes"),
                        InlineKeyboardButton("❌ No (default)", callback_data=f"pdfq_ex_{uid}_no"),
                    ]]),
                )
        elif step == "shufflecount":
            sess["shuffle_o_count"] = 0 if value == "all" else int(value)
            label = "All" if value == "all" else f"First {value}"
            await msg.edit_text(
                f"✅ Options shuffle range: {label}\n\n\U0001F4A1 Show explanation after each question?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Yes", callback_data=f"pdfq_ex_{uid}_yes"),
                    InlineKeyboardButton("❌ No (default)", callback_data=f"pdfq_ex_{uid}_no"),
                ]]),
            )
        elif step == "ex":
            sess["show_explanation"] = value == "yes"
            questions = sess.get("questions", [])
            neg_str = "None" if sess["neg"] == 0 else f"-{sess['neg']}"
            slbl = "Both" if (sess.get("shuffle_q") and sess.get("shuffle_o")) else "Questions" if sess.get("shuffle_q") else "Options" if sess.get("shuffle_o") else "None"
            await msg.edit_text(
                f"\U0001F4C4 <b>PDF Quiz Ready!</b>\n\n\U0001F4CB <b>Questions:</b> {len(questions)}\n"
                f"⏱ <b>Timer:</b> {sess['timer']}s\n✅ <b>Correct:</b> +{sess['cm']}\n➖ <b>Negative:</b> {neg_str}\n"
                f"\U0001F500 <b>Shuffle:</b> {slbl}\n\U0001F4A1 <b>Explanation:</b> {'✅ Yes' if sess['show_explanation'] else '❌ No'}\n\n▶️ Starting quiz...",
                parse_mode=ParseMode.HTML,
            )
            chat_id = sess.get("chat_id", uid)
            chat_type = sess.get("chat_type", "private")
            show_expl = sess.get("show_explanation", False)
            PDF_QUIZ_SESSIONS.pop(uid, None)
            await remove_file(sess.get("pdf_path", ""))
            await asyncio.sleep(1)
            await _launch_ai_quiz(
                uid, ctx, questions, "PDF Quiz", sess["timer"], sess["neg"], sess["cm"],
                sess.get("shuffle_q", False), sess.get("shuffle_o", False),
                shuffle_o_count=sess.get("shuffle_o_count", 0), chat_id=chat_id,
                chat_type=chat_type, update=update, show_explanation=show_expl,
            )
    except Exception as e:
        logger.error("pdfquiz_callback error: %s", e, exc_info=True)


async def _pdfquiz_generate_flow(uid: int, ctx: ContextTypes.DEFAULT_TYPE, msg: Any, sess: dict) -> None:
    """Page-by-page generation: extract each page as a single-page PDF via
    fitz (offloaded to an executor), base64-encode it, send to Gemini
    vision, and collect the returned questions."""
    pdf_path = sess["pdf_path"]
    start_p = sess["page_start"]
    end_p = sess["page_end"]
    total_q = sess["count"]
    diff = sess["diff"]
    exam = sess["exam"]
    lang = sess["lang"]
    gemini_key = sess["gemini_key"]

    try:
        import fitz
    except ImportError:
        await msg.edit_text("❌ PyMuPDF not installed.\nAsk admin: <code>pip install PyMuPDF</code>", parse_mode=ParseMode.HTML)
        PDF_QUIZ_SESSIONS.pop(uid, None)
        return

    loop = asyncio.get_running_loop()

    def _open_doc():
        return fitz.open(pdf_path)

    def _extract_page_bytes(doc, page_idx: int) -> bytes:
        one_page = fitz.open()
        one_page.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
        data = one_page.tobytes()
        one_page.close()
        return data

    try:
        src_doc = await loop.run_in_executor(None, _open_doc)
        total_pages_in_range = end_p - start_p + 1
        q_per_page = max(1, round(total_q / total_pages_in_range))
        all_questions: list[dict] = []

        for page_idx in range(start_p - 1, min(end_p, src_doc.page_count)):
            page_num = page_idx + 1
            got_so_far = len(all_questions)
            try:
                await msg.edit_text(
                    f"\U0001F50D <b>Processing page {page_num}</b> ({page_num - start_p + 1}/{total_pages_in_range})\n\n"
                    f"\U0001F4CB Questions collected so far: <b>{got_so_far}</b> / {total_q}\n⏳ Sending page to Gemini...",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

            still_needed = total_q - len(all_questions)
            hint = min(q_per_page, still_needed)
            if hint <= 0:
                break

            page_bytes = await loop.run_in_executor(None, _extract_page_bytes, src_doc, page_idx)
            page_b64 = base64.b64encode(page_bytes).decode("utf-8")

            try:
                page_questions = await gemini_page_questions(gemini_key, page_b64, page_num, hint, diff, exam, lang)
                all_questions.extend(page_questions)
            except Exception as e:
                logger.warning("Page %d generation failed: %s", page_num, e)

            await asyncio.sleep(0.5)

        await loop.run_in_executor(None, src_doc.close)

        if not all_questions:
            await msg.edit_text("❌ No questions generated. The PDF may be empty or unreadable.\nTry a different page range.", parse_mode=ParseMode.HTML)
            PDF_QUIZ_SESSIONS.pop(uid, None)
            return

        all_questions = all_questions[:total_q]
        preview = f"✅ <b>{len(all_questions)} questions from PDF!</b>\n\n\U0001F4C4 Pages {start_p}–{end_p} | {total_pages_in_range} page(s) scanned\n\n<b>Preview:</b>\n"
        for i, q in enumerate(all_questions[:2], 1):
            cids = q["correct_option_id"] if isinstance(q["correct_option_id"], list) else [q["correct_option_id"]]
            preview += f"\n<b>Q{i}.</b> {q['question'][:80]}{'...' if len(q['question']) > 80 else ''}\n"
            for j, opt in enumerate(q["options"]):
                mark = "✅" if j in cids else "▪️"
                preview += f"  {mark} {opt[:45]}\n"
        preview += "\n⏱ <b>Timer per question?</b>"

        sess["questions"] = all_questions
        PDF_QUIZ_SESSIONS[uid] = sess

        timer_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{t}s", callback_data=f"pdfq_timer_{uid}_{t}") for t in (10, 15, 20)],
            [InlineKeyboardButton(f"{t}s", callback_data=f"pdfq_timer_{uid}_{t}") for t in (25, 30, 45)],
        ])
        await msg.edit_text(preview, parse_mode=ParseMode.HTML, reply_markup=timer_kb)
    except Exception as e:
        logger.error("_pdfquiz_generate_flow error: %s", e, exc_info=True)
        await msg.edit_text(f"❌ Generation error: {str(e)[:300]}")
        PDF_QUIZ_SESSIONS.pop(uid, None)
        await remove_file(pdf_path)


def register(application: Application) -> None:
    application.add_handler(CommandHandler("pdfquiz", pdfquiz_command))
    application.add_handler(CallbackQueryHandler(pdfquiz_callback, pattern="^pdfq_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, pdfquiz_text_gate))
