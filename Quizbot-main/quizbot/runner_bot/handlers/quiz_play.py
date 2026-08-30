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
import tempfile
import time
from typing import Any, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Poll, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler

from quizbot.database import (
    AttemptRepository,
    LeaderboardRepository,
    MistakeRepository,
    QuestionStatsRepository,
    QuizRepository,
    get_db,
)
from quizbot.shared import config
from quizbot.shared.html.quiz_report import render_quiz_html
from quizbot.shared.mini_app_link import mini_app_web_app_button_ptb
from quizbot.shared.rich_quiz import (
    RichDispatchResult,
    _is_rich,
    _normalise_math_spacing,
    enrich_question_dispatch,
    send_rich_or_fallback,
)
from quizbot.shared.utils import is_premium_user

from ..pdf_reports import render_quiz_pdf
from ..quiz_utils import (
    get_section_for_question,
    is_correct,
    resolve_quiz_access,
    section_marks,
    shuffle_options_multi,
)
from ..state import channel_poll_tasks, rate_limiter, session_mgr, tasks, translation_mgr
from ..telegram_utils import (
    _get_topic_thread_id,
    prepare_poll_data,
    safe_send_message,
    safe_send_poll,
    send_raw_api,
)

logger = logging.getLogger(__name__)

_ANON_ADMIN_ID = 1087968824  # Telegram's fake @GroupAnonymousBot user id.

# How often (every N questions) to auto-post a mid-quiz leaderboard. 0 disables it.
MID_QUIZ_LB_INTERVAL = 10

# Anti-cheat pattern-detection tuning (not part of shared config -- specific
# to this handler's group-quiz cheat check, separate from CHEAT_SPEED_THRESHOLD).
CHEAT_CHECK_EVERY = 10
CHEAT_WRONG_RATIO = 0.5


def _is_anon_admin(message) -> bool:
    return message.sender_chat is not None or (
        message.from_user is not None and message.from_user.id == _ANON_ADMIN_ID
    )


async def _require_admin(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: Optional[int], is_anon: bool) -> bool:
    """Return True if the caller may run admin-only quiz-control commands."""
    if is_anon:
        return True  # Telegram only delivers anonymous-admin commands from actual admins.
    try:
        member = await ctx.bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def translate_text(text: str, target_lang: str) -> str:
    """Translate text via deep-translator (lazy import). Falls back to the
    original text on any failure so translation is never fatal to a quiz."""
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        logger.warning("deep_translator not installed; translation skipped")
        return text
    if not text or not text.strip():
        return text
    try:
        max_len = 5000
        if len(text) <= max_len:
            return GoogleTranslator(source="auto", target=target_lang).translate(text)
        parts, current = [], ""
        for para in text.split("\n"):
            if len(current) + len(para) + 1 <= max_len:
                current = f"{current}\n{para}" if current else para
            else:
                if current:
                    parts.append(current)
                current = para
        if current:
            parts.append(current)
        translated = [
            GoogleTranslator(source="auto", target=target_lang).translate(p) for p in parts if p.strip()
        ]
        return "\n".join(translated)
    except Exception as e:
        logger.error("Translation error: %s", e)
        return text


async def translate_question(qdata: dict, target_lang: str) -> dict:
    t = qdata.copy()
    try:
        if "question" in qdata:
            t["question"] = await translate_text(qdata["question"], target_lang)
        if isinstance(qdata.get("options"), list):
            t["options"] = [await translate_text(o, target_lang) for o in qdata["options"]]
        if qdata.get("reply_text"):
            t["reply_text"] = await translate_text(qdata["reply_text"], target_lang)
        if qdata.get("explanation"):
            t["explanation"] = await translate_text(qdata["explanation"], target_lang)
    except Exception as e:
        logger.error("translate_question error: %s", e)
        return qdata
    return t


async def wait_until_resumed(chat_id: int) -> None:
    while True:
        s = session_mgr.get(chat_id)
        if not s or not s.get("paused"):
            return
        await asyncio.sleep(1.5)


def _apply_char_boost(q: dict, timer: int) -> int:
    """Long questions get a little extra reading time when the timer is
    already short: >600 chars -> +30s, >450 chars -> +20s."""
    total_chars = len(q.get("question", ""))
    for opt in q.get("options", []):
        total_chars += len(opt)
    total_chars += len(q.get("reply_text") or "")
    if timer < 30:
        if total_chars > 600:
            timer += 30
        elif total_chars > 450:
            timer += 20
    return timer


# ═══════════════════════════════════════════════════════════════════════════
# PRIVATE (DM) QUIZ
# ═══════════════════════════════════════════════════════════════════════════

async def start_private_quiz(
    chat_id: int, ctx: ContextTypes.DEFAULT_TYPE, questions: list[dict], quiz: dict, qid: str, skip: int = 0
) -> None:
    """Begin a one-on-one DM quiz session."""
    try:
        data = {
            "quiz_id": qid, "current_index": skip, "paused": False,
            "questions": questions, "quiz_data": quiz, "is_private": True,
            "participants": {chat_id: {"name": "You", "answers": {}, "start_time": time.time()}},
            "waiting_for_answer": False, "active_poll_id": None,
            "polls": {}, "section_msgs": [], "current_section": None,
            "sections": quiz.get("sections", []), "context": ctx,
            "modified_timer_offset": 0,
        }
        await session_mgr.create(chat_id, data)

        sections = quiz.get("sections", [])
        if sections:
            sections.sort(key=lambda s: s["question_range"][0])
            start_sec = next((sec for sec in sections if skip < sec["question_range"][1]), None)
            if start_sec:
                await _private_section_start(chat_id, start_sec, skip)
            else:
                await safe_send_message(ctx, chat_id, "⚠️ Skip count beyond all sections.")
                await session_mgr.delete(chat_id)
        else:
            await send_private_question(chat_id, ctx, skip)
    except Exception as e:
        logger.error("start_private_quiz error: %s", e, exc_info=True)
        await safe_send_message(ctx, chat_id, "❌ Error starting quiz.")
        await session_mgr.delete(chat_id)


async def _private_section_start(chat_id: int, section: dict, skip: int = 0) -> None:
    s = session_mgr.get(chat_id)
    if not s or s.get("paused"):
        return
    start_idx, end_idx = section["question_range"]
    name = section.get("name", f"Section {start_idx}-{end_idx}")
    timer = section.get("timer", s["quiz_data"]["timer"])
    ctx = s["context"]
    msg = await safe_send_message(
        ctx, chat_id,
        f"\U0001F4DA <b>{name}</b> started\n⏱️ Timer: {timer}s\n\U0001F4CB Q{start_idx}–{end_idx}",
        parse_mode=ParseMode.HTML,
    )
    if msg:
        s["section_msgs"].append(msg.message_id)
        s["current_section"] = section
        s["current_section_timer"] = timer
        await session_mgr.update(chat_id, s)
        first = max(skip, start_idx - 1)
        await send_private_question(chat_id, ctx, first)


async def send_private_question(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    try:
        s = session_mgr.get(chat_id)
        if not s:
            return
        await wait_until_resumed(chat_id)

        questions = s["questions"]
        if idx >= len(questions):
            await end_private_quiz(chat_id, ctx)
            return

        cur_section = s.get("current_section")
        if cur_section and idx + 1 > cur_section["question_range"][1] - 1:
            s["is_last_in_section"] = True
            await session_mgr.update(chat_id, s)

        q = questions[idx]
        original_q = q.copy()

        target_lang = translation_mgr.get_language(chat_id)
        if target_lang:
            q = await translate_question(q, target_lang)

        options = q["options"]
        correct_id = q["correct_option_id"]
        correct_ids = correct_id if isinstance(correct_id, list) else [correct_id]
        is_multi = len(correct_ids) > 1
        file_id = q.get("file_id")
        reply_text = q.get("reply_text")
        do_shuffle = s["quiz_data"].get("shuffle_options", False)
        shuffle_o_count = s["quiz_data"].get("shuffle_options_count", 0)

        if do_shuffle:
            options, correct_ids = shuffle_options_multi(options, correct_ids, shuffle_o_count)

        if target_lang and target_lang != "en":
            await safe_send_message(
                ctx, chat_id, f"\U0001F4DD <b>Original</b>\n\n{original_q['question']}", parse_mode=ParseMode.HTML
            )
            await asyncio.sleep(0.5)

        photo_msg_id = None
        if file_id:
            try:
                photo_msg = await ctx.bot.send_photo(chat_id=chat_id, photo=file_id)
                photo_msg_id = photo_msg.message_id
                await asyncio.sleep(0.3)
            except Exception:
                pass

        # -- Rich-text pre-pass -------------------------------------------
        # If the question, options, or reference text contain markup the
        # native poll UI can't render (LaTeX, GFM tables, multi-paragraph
        # HTML), pre-send that content via sendRichMessage before the poll.
        _tid = s.get("message_thread_id")
        rich_res: RichDispatchResult = await enrich_question_dispatch(
            lambda method, params: send_raw_api(ctx, method, params),
            lambda text: safe_send_message(ctx, chat_id, text, parse_mode=ParseMode.HTML),
            chat_id, q, idx, len(questions), thread_id=_tid,
        )
        if rich_res.rich_sent:
            await asyncio.sleep(0.5)

        _q_text = rich_res.poll_question_override or q["question"]
        _rt = None if rich_res.suppress_reply_text else reply_text
        poll_q, poll_opts, poll_expl, overflow, poll_desc = prepare_poll_data(
            _q_text, options, correct_ids[0], q.get("explanation"), _rt, idx, len(questions)
        )
        if rich_res.poll_options_override:
            poll_opts = rich_res.poll_options_override
        if rich_res.suppress_description:
            poll_desc = None
            overflow = None

        if overflow:
            await safe_send_message(ctx, chat_id, overflow, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.5)

        timer = s.get("current_section_timer", s["quiz_data"]["timer"])
        timer += s.get("modified_timer_offset", 0)
        timer = max(timer, 10)

        poll_kwargs: dict[str, Any] = {}
        if is_multi:
            poll_kwargs["correct_option_ids"] = correct_ids
            poll_kwargs["allows_multiple_answers"] = True
        else:
            poll_kwargs["correct_option_id"] = correct_ids[0]
        if photo_msg_id:
            poll_kwargs["reply_to_message_id"] = photo_msg_id
        if poll_desc:
            poll_kwargs["description"] = poll_desc

        # Content protection (forward/save block): ON by default for every
        # private-chat play session too, and only lifted when the quiz's own
        # creator is playing it in their own DM -- same rule as the group
        # path in start_quiz() (`protect = not (chat_id == creator_id and
        # chat_type == "private")`). In a private chat chat_id IS the
        # player's own user id, so this comparison is exact.
        protect = not (chat_id == s["quiz_data"].get("creator_id"))

        poll_msg = await safe_send_poll(
            ctx, chat_id, question=poll_q, options=poll_opts, type=Poll.QUIZ,
            explanation=poll_expl, is_anonymous=False, open_period=timer,
            protect_content=protect, **poll_kwargs,
        )

        if poll_msg:
            s["active_poll_id"] = poll_msg.poll.id
            s["waiting_for_answer"] = True
            s["poll_start_time"] = time.time()
            s["current_index"] = idx
            s["polls"][poll_msg.poll.id] = {
                "correct_option": correct_ids, "sent_time": time.time(), "question_index": idx,
            }
            await session_mgr.update(chat_id, s)
            tasks.spawn(_private_timeout(chat_id, poll_msg.poll.id, timer), name=f"quiz_{chat_id}_pvt_timeout")
        elif idx + 1 < len(questions):
            await asyncio.sleep(2)
            await send_private_question(chat_id, ctx, idx + 1)
        else:
            await end_private_quiz(chat_id, ctx)
    except Exception as e:
        logger.error("send_private_question error: %s", e, exc_info=True)
        s = session_mgr.get(chat_id)
        if s and idx + 1 < len(s.get("questions", [])):
            await asyncio.sleep(2)
            await send_private_question(chat_id, ctx, idx + 1)


async def _private_timeout(chat_id: int, poll_id: str, timer: int) -> None:
    await asyncio.sleep(timer + 2)
    s = session_mgr.get(chat_id)
    if not s or s.get("active_poll_id") != poll_id:
        return
    s["waiting_for_answer"] = False
    cur = s.get("current_index", 0)
    s["current_index"] = cur + 1
    await session_mgr.update(chat_id, s)

    ctx = s.get("context")
    if ctx and s.get("quiz_data", {}).get("show_explanation"):
        await _send_explanation_after_poll(ctx, chat_id, s["questions"][cur], thread_id=s.get("message_thread_id"))

    if s.get("is_last_in_section"):
        s["is_last_in_section"] = False
        await session_mgr.update(chat_id, s)
        await _end_private_section(chat_id)
    elif ctx and cur + 1 < len(s.get("questions", [])):
        await asyncio.sleep(1)
        await send_private_question(chat_id, ctx, cur + 1)
    else:
        await end_private_quiz(chat_id, ctx)


async def handle_private_poll_answer(poll_id: str, user_id: int, option_ids: list, current_time: float) -> None:
    for chat_id in list(session_mgr.sessions.keys()):
        s = session_mgr.get(chat_id)
        if not s or not s.get("is_private") or poll_id != s.get("active_poll_id"):
            continue

        if user_id not in s["participants"]:
            s["participants"][user_id] = {"name": "You", "answers": {}}
        s["participants"][user_id]["answers"][poll_id] = {"option": option_ids, "time": current_time}
        s["waiting_for_answer"] = False
        cur = s.get("current_index", 0)
        await session_mgr.update(chat_id, s)

        ctx = s.get("context")
        if ctx and s.get("quiz_data", {}).get("show_explanation"):
            await _send_explanation_after_poll(ctx, chat_id, s["questions"][cur], thread_id=s.get("message_thread_id"))

        if s.get("is_last_in_section"):
            s["is_last_in_section"] = False
            await session_mgr.update(chat_id, s)
            await asyncio.sleep(1.5)
            await _end_private_section(chat_id)
        else:
            await asyncio.sleep(1.5)
            if ctx and cur + 1 < len(s.get("questions", [])):
                await send_private_question(chat_id, ctx, cur + 1)
            else:
                await end_private_quiz(chat_id, ctx)
        return


async def _end_private_section(chat_id: int) -> None:
    s = session_mgr.get(chat_id)
    if not s:
        return
    ctx = s.get("context")
    if s.get("section_msgs"):
        try:
            await ctx.bot.unpin_chat_message(chat_id, s["section_msgs"][-1])
        except Exception:
            pass
    sections = s.get("sections", [])
    cur_sec = s.get("current_section")
    if cur_sec and sections:
        cur_end = cur_sec["question_range"][1]
        nxt = next((sec for sec in sections if sec["question_range"][0] > cur_end), None)
        if nxt:
            await _private_section_start(chat_id, nxt, 0)
            return
    await end_private_quiz(chat_id, ctx)


async def end_private_quiz(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        s = await session_mgr.delete(chat_id)
        if not s:
            return
        quiz_data = s["quiz_data"]
        questions = s["questions"]
        total = len(questions)
        neg = quiz_data.get("negative_marking", 0)
        correct_mark = quiz_data.get("correct_mark", 1)

        await safe_send_message(ctx, chat_id, "\U0001F4CA Calculating results...")

        udata = s["participants"].get(chat_id, {})
        correct = wrong = 0
        total_time = 0.0
        for pid, pinfo in s.get("polls", {}).items():
            if pid in udata.get("answers", {}):
                ans = udata["answers"][pid]
                total_time += ans["time"] - pinfo["sent_time"]
                if is_correct(ans["option"], pinfo["correct_option"]):
                    correct += 1
                else:
                    wrong += 1

        score = (correct * correct_mark) - (wrong * neg)
        pct = (correct / total * 100) if total else 0
        acc = (correct / (correct + wrong) * 100) if (correct + wrong) else 0
        minutes, seconds = divmod(total_time, 60)

        qid = quiz_data["question_set_id"]
        buttons = [[InlineKeyboardButton("\U0001F504 Restart", url=f"https://t.me/share/url?url=/start {qid}")]]

        qname = quiz_data.get("quiz_name", "Unnamed Quiz")
        txt = (
            f"\U0001F3C6 <b>Quiz Completed!</b>\n\n"
            f"\U0001F4DD Quiz: {qname}\n\U0001F4CA Total: {total}\n\n"
            f"\U0001F4C8 <b>Your Performance:</b>\n"
            f"✅ Correct: {correct}\n❌ Wrong: {wrong}\n"
            f"\U0001F3AF Score: {score:.2f}\n⏱️ Time: {int(minutes)}m {int(seconds)}s\n"
            f"\U0001F4CA Percentage: {pct:.1f}%\n\U0001F3AF Accuracy: {acc:.1f}%"
        )
        await safe_send_message(ctx, chat_id, txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))

        await _record_attempt_and_report(
            ctx, chat_id, quiz_data, [{
                "user_id": chat_id, "name": "You", "correct": correct, "wrong": wrong,
                "score": score, "total_time": total_time, "answers": udata.get("answers", {}),
            }], chat_title="Direct Message", protect_type=False, thread_id=None,
        )
    except Exception as e:
        logger.error("end_private_quiz error: %s", e, exc_info=True)
        await safe_send_message(ctx, chat_id, "❌ Error generating results.")


# ═══════════════════════════════════════════════════════════════════════════
# GROUP QUIZ
# ═══════════════════════════════════════════════════════════════════════════

async def run_group_quiz(
    chat_id: int, ctx: ContextTypes.DEFAULT_TYPE, questions: list[dict], quiz: dict,
    protect_type: bool, update: Any, skip: int = 0,
) -> None:
    """Main group quiz loop -- one long-lived coroutine per running quiz."""
    try:
        sections = quiz.get("sections", [])
        if sections:
            sections.sort(key=lambda s: s["question_range"][0])
            await _run_sectioned_quiz(chat_id, ctx, questions, quiz, sections, protect_type, update, skip)
        else:
            await _run_flat_quiz(chat_id, ctx, questions, quiz, protect_type, update, skip)
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.error("run_group_quiz fatal error chat=%s: %s", chat_id, e, exc_info=True)
        await safe_send_message(ctx, chat_id, f"❌ Quiz error: {e}")


async def _run_flat_quiz(chat_id, ctx, questions, quiz, protect, update, skip) -> None:
    total = len(questions)
    base_timer = quiz["timer"]
    do_shuffle = quiz.get("shuffle_options", False)
    promo = quiz.get("promo_message", "")

    for idx in range(skip, total):
        session = session_mgr.get(chat_id)
        if not session:
            return
        await wait_until_resumed(chat_id)
        session = session_mgr.get(chat_id)
        if not session:
            return

        success = await _send_group_question(chat_id, ctx, questions, idx, total, base_timer, do_shuffle, protect, session)
        if not success:
            await safe_send_message(ctx, chat_id, f"⚠️ Skipped Q{idx + 1} (send error)")
            await asyncio.sleep(2)
            continue

        timer = max(base_timer + session.get("modified_timer_offset", 0), 10)
        timer = _apply_char_boost(questions[idx], timer)
        await asyncio.sleep(timer + 2)

        if quiz.get("show_explanation"):
            await _send_explanation_after_poll(ctx, chat_id, questions[idx], thread_id=session.get("message_thread_id"))

        if promo and (idx + 1) % 10 == 0 and (idx + 1) < total:
            await safe_send_message(ctx, chat_id, promo)
            await asyncio.sleep(1)

        if MID_QUIZ_LB_INTERVAL > 0 and (idx + 1) % MID_QUIZ_LB_INTERVAL == 0 and (idx + 1) < total:
            await _send_mid_quiz_leaderboard(chat_id, ctx, idx + 1, total)
            await asyncio.sleep(1)

    await _end_group_quiz(chat_id, ctx, update, quiz, protect)


async def _run_sectioned_quiz(chat_id, ctx, questions, quiz, sections, protect, update, skip) -> None:
    base_timer = quiz["timer"]
    do_shuffle = quiz.get("shuffle_options", False)
    promo = quiz.get("promo_message", "")
    q_count = 0

    start_sec_idx = 0
    for i, sec in enumerate(sections):
        if skip < sec["question_range"][1]:
            start_sec_idx = i
            break

    for sec_idx in range(start_sec_idx, len(sections)):
        section = sections[sec_idx]
        start_q, end_q = section["question_range"]
        sec_name = section.get("name", f"Section {start_q}–{end_q}")
        sec_timer = section.get("timer", base_timer)
        mode = section.get("mode", "perpoll")
        slot_mins = section.get("slot_minutes", 20)
        n_qs_sec = end_q - start_q

        session = session_mgr.get(chat_id)
        if not session:
            return

        mode_lbl = f"\U0001F550 {slot_mins} min total slot" if mode == "slot" else f"⏱ {sec_timer}s per question"
        global_cm = quiz.get("correct_mark", 1)
        global_neg = quiz.get("negative_marking", 0)
        sec_cm = section.get("correct_mark", global_cm)
        sec_neg = section.get("neg_mark", global_neg)

        sec_msg = await safe_send_message(
            ctx, chat_id,
            f"\U0001F4DA <b>{sec_name}</b>\n\U0001F4CB Q{start_q}–{end_q}  ({n_qs_sec} questions)\n"
            f"{mode_lbl}  ·  Marks: +{sec_cm} / -{sec_neg}",
            parse_mode=ParseMode.HTML,
        )
        if sec_msg:
            try:
                await ctx.bot.pin_chat_message(chat_id, sec_msg.message_id)
            except Exception:
                pass
            session.setdefault("section_msgs", []).append(sec_msg.message_id)
            await session_mgr.update(chat_id, session)

        await asyncio.sleep(1)
        first_q = max(skip if sec_idx == start_sec_idx else 0, start_q - 1)
        sec_questions = list(range(first_q, min(end_q, len(questions))))

        if mode == "slot":
            FLOOD_GAP = 3
            slot_secs = slot_mins * 60
            flood_total = max(0, len(sec_questions) - 1) * FLOOD_GAP
            slot_start = None

            for rel_idx, idx in enumerate(sec_questions):
                session = session_mgr.get(chat_id)
                if not session:
                    return
                await wait_until_resumed(chat_id)
                session = session_mgr.get(chat_id)
                if not session:
                    return

                success = await _send_group_question(chat_id, ctx, questions, idx, len(questions), 0, do_shuffle, protect, session)
                q_count += 1
                if rel_idx == 0 and success:
                    slot_start = time.time()
                if not success:
                    await safe_send_message(ctx, chat_id, f"⚠️ Skipped Q{idx + 1}")
                if rel_idx < len(sec_questions) - 1:
                    await asyncio.sleep(FLOOD_GAP)

            close_budget = len(sec_questions) * 3.5
            fair_slot = slot_secs + flood_total
            if slot_start:
                elapsed = time.time() - slot_start
                remaining = max(0, fair_slot - elapsed - close_budget)
                mins_r, secs_r = divmod(int(remaining + close_budget), 60)
                await safe_send_message(
                    ctx, chat_id,
                    f"⏳ <b>{sec_name}</b> — all {len(sec_questions)} questions sent!\n"
                    f"Section closes in <b>{mins_r}m {secs_r}s</b>.",
                    parse_mode=ParseMode.HTML,
                )
                await asyncio.sleep(remaining)

            await _close_section_polls(ctx, chat_id, sec_questions)
            await safe_send_message(
                ctx, chat_id, f"\U0001F514 <b>{sec_name}</b> — time's up! All polls closed.", parse_mode=ParseMode.HTML
            )
        else:
            for idx in sec_questions:
                session = session_mgr.get(chat_id)
                if not session:
                    return
                await wait_until_resumed(chat_id)
                session = session_mgr.get(chat_id)
                if not session:
                    return

                success = await _send_group_question(chat_id, ctx, questions, idx, len(questions), sec_timer, do_shuffle, protect, session)
                q_count += 1
                if not success:
                    await safe_send_message(ctx, chat_id, f"⚠️ Skipped Q{idx + 1}")
                    await asyncio.sleep(2)
                    continue

                timer = max(sec_timer + session.get("modified_timer_offset", 0), 10)
                timer = _apply_char_boost(questions[idx], timer)
                await asyncio.sleep(timer + 2)

                if quiz.get("show_explanation"):
                    await _send_explanation_after_poll(ctx, chat_id, questions[idx], thread_id=session.get("message_thread_id"))

                if promo and q_count % 10 == 0:
                    await safe_send_message(ctx, chat_id, promo)
                    await asyncio.sleep(1)

                if MID_QUIZ_LB_INTERVAL > 0 and q_count % MID_QUIZ_LB_INTERVAL == 0:
                    total_qs = len(quiz.get("questions", []))
                    if q_count < total_qs:
                        await _send_mid_quiz_leaderboard(chat_id, ctx, q_count, total_qs)
                        await asyncio.sleep(1)

        if sec_msg:
            try:
                await ctx.bot.unpin_chat_message(chat_id, sec_msg.message_id)
            except Exception:
                pass

    await _end_group_quiz(chat_id, ctx, update, quiz, protect)


async def _send_group_question(chat_id, ctx, questions, idx, total, base_timer, do_shuffle, protect, session) -> bool:
    """Send a single question in a group. Returns True on success."""
    try:
        q = questions[idx]
        original_q = q.copy()

        target_lang = translation_mgr.get_language(chat_id)
        if target_lang:
            q = await translate_question(q, target_lang)

        options = q["options"]
        correct_id = q["correct_option_id"]
        correct_ids = correct_id if isinstance(correct_id, list) else [correct_id]
        is_multi = len(correct_ids) > 1
        file_id = q.get("file_id")
        reply_text = q.get("reply_text")

        if do_shuffle:
            shuffle_o_count = (session.get("quiz_data") or {}).get("shuffle_options_count", 0)
            options, correct_ids = shuffle_options_multi(options, correct_ids, shuffle_o_count)

        if target_lang and target_lang != "en":
            await safe_send_message(
                ctx, chat_id, f"\U0001F4DD <b>Original</b>\n\n{original_q['question']}", parse_mode=ParseMode.HTML
            )
            await asyncio.sleep(0.5)

        photo_msg_id = None
        if file_id:
            try:
                photo_msg = await ctx.bot.send_photo(chat_id=chat_id, photo=file_id)
                photo_msg_id = photo_msg.message_id
                await asyncio.sleep(0.3)
            except Exception:
                pass

        # -- Rich-text pre-pass (see send_private_question for details) ----
        _tid = session.get("message_thread_id")
        rich_res: RichDispatchResult = await enrich_question_dispatch(
            lambda method, params: send_raw_api(ctx, method, params),
            lambda text: safe_send_message(ctx, chat_id, text, parse_mode=ParseMode.HTML),
            chat_id, q, idx, total, thread_id=_tid,
        )
        if rich_res.rich_sent:
            await asyncio.sleep(0.3)

        _q_text = rich_res.poll_question_override or q["question"]
        _rt = None if rich_res.suppress_reply_text else reply_text
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
            await asyncio.sleep(0.3)

        timer = base_timer + session.get("modified_timer_offset", 0)
        if timer > 0:
            timer = max(timer, 10)

        poll_kwargs: dict[str, Any] = {}
        if is_multi:
            poll_kwargs["correct_option_ids"] = correct_ids
            poll_kwargs["allows_multiple_answers"] = True
        else:
            poll_kwargs["correct_option_id"] = correct_ids[0]
        if photo_msg_id:
            poll_kwargs["reply_to_message_id"] = photo_msg_id
        if poll_desc:
            poll_kwargs["description"] = poll_desc

        poll_msg = await safe_send_poll(
            ctx, chat_id, question=poll_q, options=poll_opts, type=Poll.QUIZ,
            explanation=poll_expl, is_anonymous=False, open_period=timer if timer > 0 else None,
            protect_content=protect, **poll_kwargs,
        )

        if poll_msg:
            session["polls"][poll_msg.poll.id] = {
                "correct_option": correct_ids, "sent_time": time.time(),
                "question_index": idx, "message_id": poll_msg.message_id,
            }
            session["current_index"] = idx + 1
            await session_mgr.update(chat_id, session)
            return True
        return False
    except Exception as e:
        logger.error("_send_group_question error chat=%s Q%d: %s", chat_id, idx + 1, e, exc_info=True)
        return False


async def _close_section_polls(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, q_indices: list[int]) -> None:
    """Stop all open polls for a slot-mode section, respecting Telegram's
    group rate limit (~20 msgs/min => ~3s minimum gap between calls)."""
    session = session_mgr.get(chat_id)
    if not session:
        return
    polls = session.get("polls", {})
    idx_set = set(q_indices)

    to_close = [
        (pdata["message_id"], poll_id)
        for poll_id, pdata in polls.items()
        if pdata.get("question_index") in idx_set and pdata.get("message_id")
    ]
    to_close.sort(key=lambda x: x[0])

    for msg_id, poll_id in to_close:
        for _attempt in range(2):
            try:
                await ctx.bot.stop_poll(chat_id=chat_id, message_id=msg_id)
                break
            except Exception as e:
                err = str(e).lower()
                if "retry" in err or "429" in err or "flood" in err:
                    import re

                    m = re.search(r"retry.after.(\d+)", err)
                    wait = int(m.group(1)) + 1 if m else 5
                    await asyncio.sleep(wait)
                elif "poll has already been closed" in err or "message can't be modified" in err:
                    break
                else:
                    break
        await asyncio.sleep(3.5)


async def _send_mid_quiz_leaderboard(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE, q_num: int, total: int) -> None:
    try:
        session = session_mgr.get(chat_id)
        if not session:
            return
        participants = session.get("participants", {})
        polls = session.get("polls", {})
        neg = session.get("quiz_data", {}).get("negative_marking", 0)
        correct_mark = session.get("quiz_data", {}).get("correct_mark", 1)

        rows = []
        for _uid, udata in participants.items():
            correct = wrong = 0
            for pid, pdata in polls.items():
                if pid not in udata["answers"]:
                    continue
                ans = udata["answers"][pid]
                if is_correct(ans["option"], pdata["correct_option"]):
                    correct += 1
                else:
                    wrong += 1
            score = (correct * correct_mark) - (wrong * neg)
            rows.append({"name": udata["name"], "correct": correct, "wrong": wrong, "score": score})

        if not rows:
            return
        rows.sort(key=lambda x: x["score"], reverse=True)
        text = f"\U0001F4CA <b>Live Leaderboard</b> — after Q{q_num}/{total}\n{'─' * 28}\n"
        for rank, r in enumerate(rows[:10], 1):
            icon = {1: "\U0001F947", 2: "\U0001F948", 3: "\U0001F949"}.get(rank, f"{rank}.")
            text += f"{icon} <b>{str(r['name'])[:25]}</b>  ✅{r['correct']} ❌{r['wrong']}  \U0001F3AF {r['score']:.1f}\n"
        await safe_send_message(ctx, chat_id, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("_send_mid_quiz_leaderboard error: %s", e)


async def _send_explanation_after_poll(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, q: dict, thread_id: Optional[int] = None) -> None:
    """Send the post-answer explanation. Uses sendRichMessage (Bot API 10.1)
    when the explanation contains rich/math markup that the plain 4096-char
    text send would mangle or truncate too aggressively; falls back to a
    plain HTML message otherwise (or automatically, if sendRichMessage
    isn't available on the receiving client)."""
    try:
        expl = (q.get("explanation") or "").strip()
        if not expl:
            return
        await asyncio.sleep(1.5)
        kw: dict[str, Any] = {}
        if thread_id:
            kw["message_thread_id"] = thread_id

        if _is_rich(expl):
            body = _normalise_math_spacing(f"\U0001F4A1 **Explanation:**\n\n{expl}")
            await send_rich_or_fallback(
                lambda method, params: send_raw_api(ctx, method, params),
                lambda text: ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML, **kw),
                chat_id, body, thread_id=thread_id,
            )
            return

        await ctx.bot.send_message(
            chat_id=chat_id, text=f"\U0001F4A1 <b>Explanation:</b>\n\n{expl[:4000]}", parse_mode=ParseMode.HTML, **kw,
        )
    except Exception as e:
        logger.debug("_send_explanation_after_poll: %s", e)


# ═══════════════════════════════════════════════════════════════════════════
# END-OF-QUIZ SCORING / REPORTS
# ═══════════════════════════════════════════════════════════════════════════

async def _end_group_quiz(chat_id, ctx, update, quiz, protect_type) -> None:
    try:
        await end_quiz(update, ctx, quiz.get("question_set_id", ""), protect_type)
    except Exception as e:
        logger.error("_end_group_quiz error: %s", e, exc_info=True)


def _lb_rich_md(quiz_name: str, chunk: list, start_rank: int, total: int, sections: Optional[list] = None) -> str:
    """Build a GFM table leaderboard string for sendRichMessage (up to ~100
    rows per chunk), including a per-section top-5 breakdown when the quiz
    has sections. Ported from the original's `_lb_rich_md`."""
    lines = [
        f"### \U0001F3C6 {quiz_name}",
        "",
        "| # | Name | ✅ | ❌ | Score | Time | % |",
        "|--:|:-----|--:|--:|------:|-----:|--:|",
    ]
    for j, u in enumerate(chunk, start=start_rank):
        icon = "\U0001F947" if j == 1 else "\U0001F948" if j == 2 else "\U0001F949" if j == 3 else str(j)
        pct = (u["correct"] / total * 100) if total else 0
        m, sec = divmod(int(u["total_time"]), 60)
        name = str(u["name"])[:22].replace("|", "\\|")
        lines.append(
            f"| {icon} | {name} | {u['correct']} | {u['wrong']} |"
            f" {u['score']:.2f} | {int(m)}m {int(sec)}s | {pct:.0f}% |"
        )

    if sections:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("### \U0001F4DA Section Breakdown")
        lines.append("")
        for sec in sections:
            sec_name = sec.get("name", f"Section {sec['question_range'][0]}-{sec['question_range'][1]}")
            s, e = sec["question_range"]
            q_count = e - s + 1
            mode_lbl = "\U0001F550 Slot" if sec.get("mode") == "slot" else "⏱ Per-poll"
            cm_lbl = sec.get("correct_mark", "—")
            neg_lbl = sec.get("neg_mark", "—")
            timer_lbl = (
                f"{sec.get('slot_minutes')}min slot" if sec.get("mode") == "slot"
                else f"{sec.get('timer', '—')}s/poll"
            )
            lines.append(f"#### {sec_name}  ·  Q{s}–{e} ({q_count}Qs)  ·  {mode_lbl}  ·  {timer_lbl}")
            lines.append(f"Marking: **+{cm_lbl}** / **-{neg_lbl}**")
            lines.append("")

            sec_rows = []
            for u in chunk:
                sec_score = u.get("section_scores", {}).get(sec_name, {})
                sec_rows.append({
                    "name": u["name"],
                    "correct": sec_score.get("correct", 0),
                    "wrong": sec_score.get("wrong", 0),
                    "score": sec_score.get("score", 0.0),
                })
            sec_rows.sort(key=lambda x: x["score"], reverse=True)

            lines.append("| # | Name | ✅ | ❌ | Sec.Score |")
            lines.append("|--:|:-----|--:|--:|----------:|")
            for r, row in enumerate(sec_rows[:5], 1):
                icon = "\U0001F947" if r == 1 else "\U0001F948" if r == 2 else "\U0001F949" if r == 3 else f"{r}."
                lines.append(
                    f"| {icon} | {str(row['name'])[:20].replace('|', chr(92) + '|')} |"
                    f" {row['correct']} | {row['wrong']} | {row['score']:.2f} |"
                )
            lines.append("")

    return "\n".join(lines)


async def end_quiz(update: Any, ctx: ContextTypes.DEFAULT_TYPE, quiz_id: str, protect_type: bool) -> None:
    """Compute the leaderboard for a finished/stopped group quiz, post it,
    and (if enabled for this chat) generate HTML/PDF reports."""
    chat_id: Optional[int] = None
    try:
        if getattr(update, "message", None) is not None:
            chat_id = update.message.chat_id
        elif getattr(update, "callback_query", None) is not None:
            chat_id = update.callback_query.message.chat_id
        elif hasattr(update, "_chat_id"):
            chat_id = update._chat_id
        else:
            logger.error("end_quiz: cannot determine chat_id from update")
            return

        chat_title = "Quiz Group"
        try:
            chat_info = await ctx.bot.get_chat(chat_id)
            if chat_info.title:
                chat_title = chat_info.title
            elif chat_info.first_name:
                chat_title = chat_info.first_name
                if chat_info.username:
                    chat_title += f" (@{chat_info.username})"
        except Exception:
            pass

        pre_sess = session_mgr.get(chat_id)
        end_tid = pre_sess.get("message_thread_id") if pre_sess else None

        session = await session_mgr.delete(chat_id)
        msg_kwargs = {"message_thread_id": end_tid} if end_tid else {}
        placeholder = await safe_send_message(ctx, chat_id, "Generating Result...", **msg_kwargs)

        if not session or session["quiz_id"] != quiz_id:
            if placeholder:
                await placeholder.edit_text("❌ No quiz found with this ID.")
            return

        quiz_data = session.get("quiz_data")
        if not quiz_data:
            repo = QuizRepository(get_db())
            quiz_data = await repo.get(quiz_id)
        if not quiz_data:
            if placeholder:
                await placeholder.edit_text("❌ Quiz data not found.")
            return

        total = len(quiz_data["questions"])
        quiz_name = quiz_data.get("quiz_name", "Unnamed Quiz")
        neg = quiz_data.get("negative_marking", 0)
        correct_mark = quiz_data.get("correct_mark", 1)
        sections = quiz_data.get("sections", [])

        leaderboard = []
        for uid, udata in session["participants"].items():
            correct = wrong = 0
            total_time = 0.0
            user_answers: dict[str, Any] = {}
            section_scores: dict[str, dict] = {}

            for pid, pdata in session["polls"].items():
                if pid not in udata["answers"]:
                    continue
                ans = udata["answers"][pid]
                total_time += ans["time"] - pdata["sent_time"]
                q_idx = pdata.get("question_index", 0)
                user_answers[f"q{q_idx}"] = ans["option"]

                sec = get_section_for_question(sections, q_idx)
                q_cm, q_neg = section_marks(sec, correct_mark, neg)
                sec_name = sec.get("name", "default") if sec else "default"
                section_scores.setdefault(sec_name, {"correct": 0, "wrong": 0, "score": 0.0})

                if is_correct(ans["option"], pdata["correct_option"]):
                    correct += 1
                    section_scores[sec_name]["correct"] += 1
                    section_scores[sec_name]["score"] += q_cm
                else:
                    wrong += 1
                    section_scores[sec_name]["wrong"] += 1
                    section_scores[sec_name]["score"] -= q_neg

            score = (
                sum(v["score"] for v in section_scores.values())
                if section_scores else (correct * correct_mark) - (wrong * neg)
            )
            leaderboard.append({
                "user_id": uid, "name": udata["name"], "correct": correct, "wrong": wrong,
                "score": round(score, 4), "total_time": total_time, "answers": user_answers,
                "section_scores": section_scores,
            })

        if not leaderboard:
            if placeholder:
                await placeholder.edit_text(f"\U0001F3C6 Quiz '{quiz_name}' ended!\n\n❌ No answers recorded.")
            return

        leaderboard.sort(key=lambda x: (x["score"], -x["total_time"]), reverse=True)

        if placeholder:
            try:
                await placeholder.delete()
            except Exception:
                pass

        for i in range(0, len(leaderboard), 100):
            chunk = leaderboard[i:i + 100]
            if i > 0:
                await asyncio.sleep(3)
            rich_md = _lb_rich_md(quiz_name, chunk, i + 1, total, sections)
            await send_rich_or_fallback(
                lambda method, params: send_raw_api(ctx, method, params),
                lambda text: safe_send_message(ctx, chat_id, text, **msg_kwargs),
                chat_id, rich_md, thread_id=end_tid,
            )

        await _record_attempt_and_report(
            ctx, chat_id, quiz_data, leaderboard, chat_title=chat_title,
            protect_type=protect_type, thread_id=end_tid,
        )
    except Exception as e:
        logger.error("end_quiz error: %s", e, exc_info=True)
        if chat_id is not None:
            await safe_send_message(ctx, chat_id, "❌ Error generating results.")


async def _record_attempt_and_report(
    ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, quiz_data: dict, leaderboard: list[dict],
    *, chat_title: str, protect_type: bool, thread_id: Optional[int],
) -> None:
    """Persist attempts/leaderboard rows to the DB and send HTML/PDF reports
    if enabled for this chat. Replaces the old local quiz_results/*.json
    file-storage approach entirely -- everything lands in SQLite."""
    from quizbot.database import ChatSettingsRepository

    qid = quiz_data.get("question_set_id", "")
    total = len(quiz_data.get("questions", []))
    db = get_db()

    # Persist a completed attempt + leaderboard row per participant (if the
    # quiz exists in the DB -- ad-hoc AI/PDF/mix quizzes are not persisted
    # since they have no qid row to reference).
    quiz_repo = QuizRepository(db)
    quiz_exists = bool(await quiz_repo.get(qid)) if qid else False
    if quiz_exists:
        attempt_repo = AttemptRepository(db)
        mistake_repo = MistakeRepository(db)
        stats_repo = QuestionStatsRepository(db)
        wrong_by_q: dict[int, int] = {}
        total_by_q: dict[int, int] = {}

        for entry in leaderboard:
            user_id = entry["user_id"]
            if not isinstance(user_id, int):
                continue
            attempt = await attempt_repo.start(user_id, qid, quiz_data.get("quiz_name", ""), total)
            await attempt_repo.update(attempt["attempt_id"], answers=entry.get("answers", {}), score=int(entry["score"]))
            await attempt_repo.complete(attempt["attempt_id"], int(entry["score"]), str(entry["name"]))

            mistakes = []
            for q_key, ans in entry.get("answers", {}).items():
                try:
                    q_idx = int(q_key.lstrip("q"))
                except ValueError:
                    continue
                total_by_q[q_idx] = total_by_q.get(q_idx, 0) + 1
                q = quiz_data["questions"][q_idx] if q_idx < len(quiz_data["questions"]) else None
                if q and not is_correct(ans, q.get("correct_option_id")):
                    wrong_by_q[q_idx] = wrong_by_q.get(q_idx, 0) + 1
                    mistakes.append({"qid": qid, "index": q_idx})
            if mistakes:
                await mistake_repo.record(user_id, mistakes)

        if total_by_q:
            await stats_repo.bulk_update_wrong_stats(
                qid, [{"index": i, "wrong": wrong_by_q.get(i, 0), "total": n} for i, n in total_by_q.items()]
            )
        await quiz_repo.increment_participants(qid)

    chat_settings_repo = ChatSettingsRepository(db)
    chat_settings = await chat_settings_repo.get(chat_id)

    if chat_settings["html_enabled"]:
        try:
            report_quiz = {**quiz_data, "qid": qid}
            html_bytes, filename = await render_quiz_html(report_quiz, mode="exam")
            await ctx.bot.send_document(
                chat_id=chat_id, document=html_bytes, filename=filename,
                caption="\U0001F4C4 Interactive quiz report",
                **({"message_thread_id": thread_id} if thread_id else {}),
            )
        except Exception as e:
            logger.error("HTML report generation error: %s", e)

    if chat_settings["pdf_enabled"]:
        await _send_pdf_report(ctx, chat_id, quiz_data, chat_title, leaderboard, session_polls=None, thread_id=thread_id)


async def _send_pdf_report(
    ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, quiz_data: dict, chat_title: str,
    leaderboard: list[dict], session_polls: Optional[dict], thread_id: Optional[int],
) -> None:
    """Render and send a PDF quiz report, offloading WeasyPrint's
    synchronous rendering to a thread-pool executor."""
    try:
        orig_questions = quiz_data.get("questions", [])
        neg_val = quiz_data.get("negative_marking", 0)
        cm_val = quiz_data.get("correct_mark", 1)
        sections = quiz_data.get("sections", [])
        do_shuffle_opts = quiz_data.get("shuffle_options", False)

        real_polls = session_polls or {}
        sent_indices = {pdata.get("question_index") for pdata in real_polls.values()}
        full_polls = dict(real_polls)
        for q_idx in range(len(orig_questions)):
            if q_idx not in sent_indices:
                full_polls[f"__unsent_{q_idx}__"] = {"question_index": q_idx, "correct_option": [], "sent_time": 0}

        bg_image_b64 = None
        try:
            chat_obj = await ctx.bot.get_chat(chat_id)
            if getattr(chat_obj, "photo", None):
                photo_file = await ctx.bot.get_file(chat_obj.photo.small_file_id)
                photo_bytes = await photo_file.download_as_bytearray()
                bg_image_b64 = "data:image/jpeg;base64," + base64.b64encode(bytes(photo_bytes)).decode()
        except Exception:
            pass

        pdf_path = os.path.join(tempfile.gettempdir(), f"quiz_report_{chat_id}_{int(time.time())}.pdf")
        quiz_name = quiz_data.get("quiz_name", "Unnamed Quiz")

        loop = asyncio.get_running_loop()
        pdf_ok = await loop.run_in_executor(
            None, render_quiz_pdf, quiz_name, chat_title, orig_questions, leaderboard,
            full_polls, neg_val, cm_val, pdf_path, sections, bg_image_b64, do_shuffle_opts, "classic",
        )

        if pdf_ok and os.path.exists(pdf_path):
            try:
                caption = (
                    f"\U0001F4C4 <b>{quiz_name}</b>\n\U0001F4DA {chat_title}\n"
                    f"\U0001F465 {len(leaderboard)} participant(s)\n\n"
                    f"<i>Full quiz report with questions, answers &amp; results</i>"
                )
                with open(pdf_path, "rb") as pf:
                    await ctx.bot.send_document(
                        chat_id=chat_id, document=pf, filename=f"QuizReport_{quiz_name[:30]}.pdf",
                        caption=caption, parse_mode=ParseMode.HTML,
                        **({"message_thread_id": thread_id} if thread_id else {}),
                    )
            finally:
                try:
                    os.remove(pdf_path)
                except OSError:
                    pass
    except Exception as e:
        logger.error("PDF report error: %s", e, exc_info=True)


# ═══════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

async def start_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/start [quiz_id] [skip] -- launches the quiz-setup wizard, or shows a
    welcome message if no quiz id was given."""
    from .setup_wizard import show_correct_mark_prompt
    from ..state import pending_quiz_settings

    chat_id = update.message.chat_id
    try:
        chat_type = update.message.chat.type
        is_anon = _is_anon_admin(update.message)

        if is_anon and chat_type != ChatType.PRIVATE:
            qid_arg = ctx.args[0] if ctx.args else ""
            btn = InlineKeyboardMarkup([[
                InlineKeyboardButton("\U0001F464 Tap here to verify your identity", callback_data=f"qs_anon_verify_{chat_id}_{qid_arg}")
            ]])
            await safe_send_message(
                ctx, chat_id,
                "⚠️ <b>Anonymous admin detected!</b>\n\nTap the button below to verify and continue.",
                parse_mode=ParseMode.HTML, reply_markup=btn,
            )
            return

        user_id = update.message.from_user.id

        if not await is_premium_user(user_id):
            await safe_send_message(ctx, chat_id, "Please help us to make this project more valuable by purchasing premium! Thanks")
            return
        if not await rate_limiter.check(user_id):
            await safe_send_message(ctx, chat_id, "⏱️ Too many requests. Wait a moment.")
            return

        if not ctx.args:
            welcome = (
                "\U0001F44B Welcome to <b>Advance Quiz Bot</b>!\n\n"
                "Create quizzes with MCQs, sections, timers, and more.\n\n"
                "Use /help to learn usage!"
            )
            await safe_send_message(ctx, chat_id, welcome, parse_mode=ParseMode.HTML)
            return

        qid = ctx.args[0]
        skip = int(ctx.args[1]) if len(ctx.args) > 1 and ctx.args[1].isdigit() else 0

        # The inline-share "Play Quiz" button opens `?startapp=play_<qid>_
        # <mode>` (see mini_app_link.py's _startapp_payload) so it can work
        # from a context where a native web_app button isn't allowed. When
        # the Mini App is registered with BotFather, Telegram launches it
        # directly and this handler never runs. But if the Mini App isn't
        # registered yet, or the user's client doesn't support Mini Apps,
        # Telegram falls back to a plain `/start play_<qid>_<mode>` command
        # here instead -- and without unwrapping that payload first, `qid`
        # would literally be the string "play_<qid>_<mode>", which never
        # matches a real quiz id, so every fallback used to fail with
        # "Invalid QuestionSetID." Detect and unwrap it, then hand the user
        # a working native Play button (safe here since /start is always a
        # private chat) instead of silently erroring out.
        mini_app_mode: Optional[str] = None
        if qid.startswith("play_") and "_" in qid[len("play_"):]:
            body = qid[len("play_"):]
            real_qid, _, mode_part = body.rpartition("_")
            if real_qid and mode_part in ("practice", "exam"):
                qid = real_qid
                mini_app_mode = mode_part

        if session_mgr.get(chat_id):
            await safe_send_message(ctx, chat_id, "⚠️ A quiz is already running. /stop it first.")
            return

        quiz_repo = QuizRepository(get_db())
        quiz = await quiz_repo.get(qid)
        if not quiz:
            if mini_app_mode:
                await safe_send_message(
                    ctx, chat_id,
                    "❌ This quiz link has expired or the quiz was removed.",
                )
            else:
                await safe_send_message(ctx, chat_id, "❌ Invalid QuestionSetID.")
            return

        if mini_app_mode and chat_type == ChatType.PRIVATE:
            # The Mini App WebApp launch didn't happen (not registered with
            # BotFather yet, or an older client) -- offer a real native
            # web_app button here instead of silently starting the classic
            # poll-based quiz the user didn't ask for.
            label = "\U0001F3AF Play (Practice)" if mini_app_mode == "practice" else "\U0001F4DD Play (Exam)"
            play_btn = mini_app_web_app_button_ptb(qid, mini_app_mode, label)
            if play_btn:
                await safe_send_message(
                    ctx, chat_id,
                    f"✨ <b>{quiz.get('quiz_name', 'Quiz')}</b>\n\nTap below to play:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[play_btn]]),
                )
                return
            # Mini App isn't configured at all (no MINI_APP_DOMAIN) --
            # fall through to the classic poll-based quiz below so the
            # link still does *something* useful instead of a dead end.

        allowed, batch = await resolve_quiz_access(qid, quiz, chat_id, chat_type, user_id, ctx=ctx)
        if not allowed:
            await _send_access_denied(ctx, chat_id, quiz, batch)
            return

        # Content protection (forward/save block) defaults to ON for every
        # quiz -- free or paid -- and is only lifted when the creator is
        # running their own quiz in their own private chat. Matches the
        # original bot's `protect = True; if chat_id == creator_id and
        # chat_type == "private": protect = False` logic exactly.
        protect = not (chat_id == quiz.get("creator_id") and chat_type == "private")

        quiz["question_set_id"] = quiz["qid"]
        quiz["negative_marking"] = quiz.get("negative_marks", 0)
        quiz["correct_mark"] = quiz.get("correct_marks", 1)
        quiz["shuffle_options"] = bool(quiz.get("shuffle_options", False))
        quiz["shuffle"] = bool(quiz.get("shuffle_questions", False))

        cmd_thread_id = getattr(update.message, "message_thread_id", None)
        pending_quiz_settings[chat_id] = {
            "quiz": quiz, "update": update, "skip": skip,
            "protect": protect, "chat_type": chat_type,
            "correct_mark": 1.0, "neg_mark": 0.0,
            "shuffle_q": False, "shuffle_o": False,
            "show_explanation": False, "timer_override": None,
            "initiator_id": user_id, "message_thread_id": cmd_thread_id,
        }

        # Offer the visual Mini App player as an alternative to the classic
        # poll-based flow -- private chats only (web_app buttons aren't
        # valid in groups), doesn't touch pending_quiz_settings/the wizard
        # below at all, just an extra informational message. Silently
        # skipped if MINI_APP_DOMAIN isn't configured.
        if chat_type == ChatType.PRIVATE:
            play_practice = mini_app_web_app_button_ptb(qid, "practice", "\U0001F3AF Play (Practice)")
            play_exam = mini_app_web_app_button_ptb(qid, "exam", "\U0001F4DD Play (Exam)")
            if play_practice and play_exam:
                await safe_send_message(
                    ctx, chat_id,
                    "✨ You can also play this quiz visually in-app:",
                    reply_markup=InlineKeyboardMarkup([[play_practice, play_exam]]),
                )

        await show_correct_mark_prompt(ctx, chat_id)
    except Exception as e:
        logger.error("start_quiz error: %s", e, exc_info=True)
        await safe_send_message(ctx, chat_id, "❌ Error starting quiz.")


async def _send_access_denied(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, quiz: dict, batch: Optional[dict]) -> None:
    creator_id = quiz.get("creator_id")
    if batch:
        msg = f"\U0001F512 <b>Paid Quiz — Access Required</b>\n\n\U0001F4E6 Batch: <b>{batch.get('name', '')}</b>\n"
        if batch.get("description"):
            msg += f"\U0001F4DD {batch['description']}\n"
        if batch.get("payment_link"):
            msg += f"\n\U0001F4B3 <b>Pay here:</b> {batch['payment_link']}\n"
        if batch.get("contact_info"):
            msg += f"\U0001F4DE <b>Contact:</b> {batch['contact_info']}\n"
        msg += "\nAfter payment, send screenshot to the contact above."
        await safe_send_message(ctx, chat_id, msg, parse_mode=ParseMode.HTML)
    else:
        try:
            cinfo = await ctx.bot.get_chat(creator_id)
            details = f"\U0001F464 {cinfo.first_name or ''}\n\U0001F4AC @{cinfo.username or 'N/A'}\n\U0001F522 ID: {cinfo.id}"
            await safe_send_message(ctx, chat_id, f"❌ Contact the quiz creator for access.\n\n{details}")
        except Exception:
            await safe_send_message(ctx, chat_id, f"❌ Contact creator ID {creator_id} for access.")


async def stop_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/stop -- ends the running quiz in this chat (admin-only in groups)."""
    chat_id = update.message.chat.id
    try:
        chat_type = update.message.chat.type
        is_anon = _is_anon_admin(update.message)
        user_id = None if is_anon else (update.message.from_user.id if update.message.from_user else None)

        session = session_mgr.get(chat_id)
        if not session:
            await safe_send_message(ctx, chat_id, "⚠️ No quiz running.")
            return

        if chat_type == ChatType.PRIVATE:
            tasks.cancel_all_for_chat(chat_id)
            if session.get("is_private"):
                await end_private_quiz(chat_id, ctx)
            else:
                await end_quiz(update, ctx, session["quiz_id"], True)
            await session_mgr.delete(chat_id)
            await safe_send_message(ctx, chat_id, "\U0001F6AB Quiz stopped.")
            return

        if not await _require_admin(ctx, chat_id, user_id, is_anon):
            await safe_send_message(ctx, chat_id, "\U0001F6AB Admin only.")
            return

        tasks.cancel_all_for_chat(chat_id)
        qid = session["quiz_id"]
        try:
            await end_quiz(update, ctx, qid, True)
        finally:
            await session_mgr.delete(chat_id)
            await safe_send_message(ctx, chat_id, "\U0001F6AB Quiz stopped by admin.")
    except Exception as e:
        logger.error("stop_quiz error: %s", e, exc_info=True)


async def pause_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/pause -- pauses the running quiz (admin-only in groups)."""
    chat_id = update.message.chat.id
    try:
        chat_type = update.message.chat.type
        is_anon = _is_anon_admin(update.message)
        user_id = None if is_anon else (update.message.from_user.id if update.message.from_user else None)

        session = session_mgr.get(chat_id)
        if not session:
            await safe_send_message(ctx, chat_id, "⚠️ No quiz running.")
            return

        if chat_type != ChatType.PRIVATE and not await _require_admin(ctx, chat_id, user_id, is_anon):
            await safe_send_message(ctx, chat_id, "\U0001F6AB Admin only.")
            return

        await session_mgr.update(chat_id, {"paused": True})
        who = "" if chat_type == ChatType.PRIVATE else " by admin"
        await safe_send_message(ctx, chat_id, f"⏸ Paused{who}. /resume to continue.")
    except Exception as e:
        logger.error("pause_quiz error: %s", e)


async def resume_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/resume -- resumes a paused quiz (admin-only in groups)."""
    chat_id = update.message.chat.id
    try:
        chat_type = update.message.chat.type
        is_anon = _is_anon_admin(update.message)
        user_id = None if is_anon else (update.message.from_user.id if update.message.from_user else None)

        session = session_mgr.get(chat_id)
        if not session or not session.get("paused"):
            await safe_send_message(ctx, chat_id, "⚠️ No quiz paused.")
            return

        if chat_type != ChatType.PRIVATE and not await _require_admin(ctx, chat_id, user_id, is_anon):
            await safe_send_message(ctx, chat_id, "\U0001F6AB Admin only.")
            return

        await session_mgr.update(chat_id, {"paused": False})
        who = "" if chat_type == ChatType.PRIVATE else " by admin"
        await safe_send_message(ctx, chat_id, f"▶️ Resumed{who}!")

        if chat_type == ChatType.PRIVATE and session.get("is_private") and session.get("waiting_for_answer"):
            cur = session.get("current_index", 0)
            if cur < len(session.get("questions", [])):
                await send_private_question(chat_id, ctx, cur)
    except Exception as e:
        logger.error("resume_quiz error: %s", e)


async def _adjust_timer(update: Update, ctx: ContextTypes.DEFAULT_TYPE, delta: int) -> None:
    chat_id = update.message.chat.id
    chat_type = update.message.chat.type
    is_anon = _is_anon_admin(update.message)
    user_id = None if is_anon else (update.message.from_user.id if update.message.from_user else None)

    seconds = abs(delta)
    if ctx.args and ctx.args[0].isdigit():
        seconds = int(ctx.args[0])
    if delta < 0:
        seconds = -seconds

    session = session_mgr.get(chat_id)
    if not session:
        await safe_send_message(ctx, chat_id, "⚠️ No quiz running.")
        return

    if chat_type != ChatType.PRIVATE and not await _require_admin(ctx, chat_id, user_id, is_anon):
        await safe_send_message(ctx, chat_id, "\U0001F6AB Admin only.")
        return

    offset = session.get("modified_timer_offset", 0) + seconds
    await session_mgr.update(chat_id, {"modified_timer_offset": offset})
    direction = "decreased" if seconds < 0 else "increased"
    await safe_send_message(ctx, chat_id, f"⏱️ Timer {direction} by {abs(seconds)}s per question.")


async def fast_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/fast -- shortens the remaining per-question timer by 5s (or a given amount)."""
    try:
        await _adjust_timer(update, ctx, -5)
    except Exception as e:
        logger.error("fast_quiz error: %s", e)


async def slow_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/slow -- lengthens the remaining per-question timer by 5s (or a given amount)."""
    try:
        await _adjust_timer(update, ctx, 5)
    except Exception as e:
        logger.error("slow_quiz error: %s", e)


async def normal_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/normal -- resets the per-question timer offset to zero."""
    chat_id = update.message.chat.id
    try:
        chat_type = update.message.chat.type
        is_anon = _is_anon_admin(update.message)
        user_id = None if is_anon else (update.message.from_user.id if update.message.from_user else None)

        session = session_mgr.get(chat_id)
        if not session:
            await safe_send_message(ctx, chat_id, "⚠️ No quiz running.")
            return
        if chat_type != ChatType.PRIVATE and not await _require_admin(ctx, chat_id, user_id, is_anon):
            await safe_send_message(ctx, chat_id, "\U0001F6AB Admin only.")
            return

        await session_mgr.update(chat_id, {"modified_timer_offset": 0})
        await safe_send_message(ctx, chat_id, "⏱️ Timer reset to default.")
    except Exception as e:
        logger.error("normal_quiz error: %s", e)


async def leaderboard_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/leaderboard -- shows a live top-10 leaderboard for the running quiz."""
    try:
        chat_id = update.message.chat.id
        user_id = update.message.from_user.id
        chat_type = update.message.chat.type

        session = session_mgr.get(chat_id)
        if not session:
            await safe_send_message(ctx, chat_id, "⚠️ No quiz running.")
            return

        if chat_type != ChatType.PRIVATE:
            try:
                member = await ctx.bot.get_chat_member(chat_id, user_id)
                if member.status not in ("administrator", "creator"):
                    await safe_send_message(ctx, chat_id, "\U0001F6AB Admin only.")
                    return
            except Exception:
                return

        total = len(session.get("quiz_data", {}).get("questions", []))
        done = session.get("current_index", 0)
        await _send_mid_quiz_leaderboard(chat_id, ctx, done, total)
    except Exception as e:
        logger.error("leaderboard_command error: %s", e)


async def handle_poll_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """PollAnswerHandler: routes an incoming answer to the matching private
    or group session, records it, and runs anti-cheat detection for groups
    that opted in."""
    try:
        pa = update.poll_answer
        poll_id = pa.poll_id
        user_id = pa.user.id
        user_name = pa.user.first_name
        option_ids = list(pa.option_ids)
        now = time.time()

        for cid in list(session_mgr.sessions.keys()):
            s = session_mgr.get(cid)
            if s and s.get("is_private") and poll_id == s.get("active_poll_id"):
                if not option_ids:
                    if user_id in s.get("participants", {}):
                        s["participants"][user_id]["answers"].pop(poll_id, None)
                        await session_mgr.update(cid, s)
                    return
                await handle_private_poll_answer(poll_id, user_id, option_ids, now)
                return

        for cid in list(session_mgr.sessions.keys()):
            s = session_mgr.get(cid)
            if not s or s.get("is_private"):
                continue
            if poll_id not in s.get("polls", {}):
                continue

            if not option_ids:
                if user_id in s.get("participants", {}):
                    s["participants"][user_id]["answers"].pop(poll_id, None)
                    await session_mgr.update(cid, s)
                return

            correct = s["polls"][poll_id].get("correct_option")
            is_multi_poll = isinstance(correct, list) and len(correct) > 1

            if user_id not in s["participants"]:
                s["participants"][user_id] = {"name": user_name, "answers": {}}
            s["participants"][user_id]["answers"][poll_id] = {"option": option_ids, "time": now, "is_multi": is_multi_poll}
            await session_mgr.update(cid, s)

            if s.get("anti_cheat"):
                await _check_anti_cheat(ctx, cid, s, poll_id, user_id, user_name, option_ids, correct, now)
            return
    except Exception as e:
        logger.error("handle_poll_answer error: %s", e, exc_info=True)


async def _check_anti_cheat(
    ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, session: dict, poll_id: str,
    user_id: int, user_name: str, option_ids: list, correct: Any, now: float,
) -> None:
    """Speed+accuracy pattern check: users who repeatedly answer faster than
    config.CHEAT_SPEED_THRESHOLD *and* get it wrong are flagged as likely
    running a duplicate/bot account and auto-kicked past a suspicion ratio."""
    pinfo = session["polls"][poll_id]
    sent_time = pinfo.get("sent_time", now)
    answer_time = now - sent_time
    correct_answer = is_correct(option_ids, correct)
    fast_and_wrong = answer_time < config.CHEAT_SPEED_THRESHOLD and not correct_answer

    p_entry = session["participants"][user_id]
    ct = p_entry.setdefault("cheat_track", {"suspicious": 0, "total": 0})
    ct["total"] += 1
    if fast_and_wrong:
        ct["suspicious"] += 1
    await session_mgr.update(chat_id, session)

    if ct["total"] % CHEAT_CHECK_EVERY != 0:
        return
    sus_ratio = ct["suspicious"] / ct["total"]
    if sus_ratio < CHEAT_WRONG_RATIO:
        return
    try:
        await ctx.bot.ban_chat_member(chat_id, user_id)
        await safe_send_message(
            ctx, chat_id,
            f"\U0001F6AB <b>{user_name}</b> was removed from the group!\n\n"
            f"<i>Suspicious rapid-wrong-answer pattern detected (possible duplicate account).</i>",
            parse_mode=ParseMode.HTML,
        )
        logger.warning("Cheater kicked: uid=%s name=%s cid=%s suspicious=%.0f%%", user_id, user_name, chat_id, sus_ratio * 100)
    except Exception as e:
        logger.error("Failed to kick cheater uid=%s: %s", user_id, e)


def register(application: Application) -> None:
    """Register all quiz-play command/poll handlers on the given Application."""
    application.add_handler(CommandHandler("start", start_quiz))
    application.add_handler(CommandHandler("pause", pause_quiz))
    application.add_handler(CommandHandler("resume", resume_quiz))
    application.add_handler(CommandHandler("stop", stop_quiz))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("slow", slow_quiz))
    application.add_handler(CommandHandler("fast", fast_quiz))
    application.add_handler(CommandHandler("normal", normal_quiz))
    application.add_handler(PollAnswerHandler(handle_poll_answer))
