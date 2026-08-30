"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from quizbot.database import QuizPrefsRepository, get_db
from quizbot.shared.utils import is_premium_user

from ..quiz_utils import check_batch_access, resolve_quiz_access
from ..state import pending_quiz_settings, rate_limiter, session_mgr, tasks
from ..telegram_utils import safe_send_message

logger = logging.getLogger(__name__)

_QUIZ_PREFS_DEFAULTS = {
    "correct_mark": 1.0, "neg_mark": 0.0,
    "shuffle_q": False, "shuffle_o": False, "shuffle_o_count": 0,
    "show_explanation": False, "anti_cheat": False, "timer_override": None,
}


async def _get_quiz_prefs(chat_id: int) -> dict:
    """This chat's last-used quiz settings, or hardcoded defaults if none
    are saved yet. `is_default` is True when no saved row existed."""
    try:
        repo = QuizPrefsRepository(get_db())
        row = await repo.get(chat_id)
        is_default = row.get("updated_at") is None
        merged = {**_QUIZ_PREFS_DEFAULTS, **{k: row[k] for k in _QUIZ_PREFS_DEFAULTS if k in row}}
        for bool_key in ("shuffle_q", "shuffle_o", "show_explanation", "anti_cheat"):
            merged[bool_key] = bool(merged[bool_key])
        merged["is_default"] = is_default
        return merged
    except Exception as e:
        logger.error("_get_quiz_prefs error: %s", e)
        return {**_QUIZ_PREFS_DEFAULTS, "is_default": True}


async def _save_quiz_prefs(chat_id: int, prefs: dict) -> None:
    """Best-effort upsert of this chat's last-used settings. Never raises --
    a failed save must not break an in-progress quiz launch."""
    try:
        repo = QuizPrefsRepository(get_db())
        await repo.save(chat_id, **prefs)
    except Exception as e:
        logger.error("_save_quiz_prefs error: %s", e)


async def _setup_edit(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, kb: InlineKeyboardMarkup) -> None:
    """Edit the single setup message in place, or send it if not created yet."""
    ps = pending_quiz_settings.get(chat_id, {})
    msg_id = ps.get("setup_msg_id")
    if msg_id:
        try:
            await ctx.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        except Exception:
            pass
    msg = await safe_send_message(ctx, chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb)
    if msg and chat_id in pending_quiz_settings:
        pending_quiz_settings[chat_id]["setup_msg_id"] = msg.message_id


async def show_correct_mark_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Step 1: correct mark per question, with a Quick Start shortcut."""
    prev = await _get_quiz_prefs(chat_id)
    has_saved = not prev.get("is_default", True)
    qs_label = "⚡ Quick Start (your last settings)" if has_saved else "⚡ Quick Start (all defaults)"
    qs_desc = "your last-used settings" if has_saved else "all defaults"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(str(n), callback_data=f"qs_cm_{chat_id}_{n}") for n in range(1, 6)],
        [InlineKeyboardButton("⏭ Skip (default 1)", callback_data=f"qs_cm_{chat_id}_skip")],
        [InlineKeyboardButton(qs_label, callback_data=f"qs_qs_{chat_id}_go")],
    ])
    msg = await safe_send_message(
        ctx, chat_id,
        f"\U0001F3AF <b>Correct mark per question?</b>\n\nOr tap <b>⚡ Quick Start</b> to launch immediately with {qs_desc}.",
        parse_mode=ParseMode.HTML, reply_markup=kb,
    )
    if msg and chat_id in pending_quiz_settings:
        pending_quiz_settings[chat_id]["setup_msg_id"] = msg.message_id


async def _show_neg_mark_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, correct_mark: float) -> None:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1/4", callback_data=f"qs_nm_{chat_id}_0.25"),
         InlineKeyboardButton("1/3", callback_data=f"qs_nm_{chat_id}_0.333"),
         InlineKeyboardButton("1/2", callback_data=f"qs_nm_{chat_id}_0.5"),
         InlineKeyboardButton("1", callback_data=f"qs_nm_{chat_id}_1.0")],
        [InlineKeyboardButton("⏭ Skip (no negative)", callback_data=f"qs_nm_{chat_id}_skip")],
    ])
    await _setup_edit(ctx, chat_id, f"➖ <b>Negative marking?</b> (applied on correct mark {correct_mark})", kb)


async def _show_shuffle_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001F500 Questions", callback_data=f"qs_sh_{chat_id}_q"),
         InlineKeyboardButton("\U0001F500 Options", callback_data=f"qs_sh_{chat_id}_o"),
         InlineKeyboardButton("\U0001F500 Both", callback_data=f"qs_sh_{chat_id}_b")],
        [InlineKeyboardButton("⏭ No Shuffle", callback_data=f"qs_sh_{chat_id}_skip")],
    ])
    await _setup_edit(ctx, chat_id, "\U0001F500 <b>Shuffle?</b>", kb)


async def _show_shuffle_count_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("First 2", callback_data=f"qs_shc_{chat_id}_2"),
         InlineKeyboardButton("First 4", callback_data=f"qs_shc_{chat_id}_4")],
        [InlineKeyboardButton("All", callback_data=f"qs_shc_{chat_id}_all")],
    ])
    await _setup_edit(
        ctx, chat_id,
        "\U0001F500 <b>Shuffle how many options?</b>\nOnly the first N option positions will be "
        "shuffled among themselves — the rest stay put.",
        kb,
    )


async def _show_timer_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    ps = pending_quiz_settings.get(chat_id, {})
    quiz_default = ps.get("quiz", {}).get("timer", 30)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{t}s", callback_data=f"qs_tm_{chat_id}_{t}") for t in (10, 15, 20)],
        [InlineKeyboardButton(f"{t}s", callback_data=f"qs_tm_{chat_id}_{t}") for t in (25, 30, 40)],
        [InlineKeyboardButton(f"⏭ Quiz default ({quiz_default}s)", callback_data=f"qs_tm_{chat_id}_default")],
    ])
    await _setup_edit(ctx, chat_id, "⏱ <b>Timer per question?</b>\n\nSelect a time — Start button will appear after.", kb)


async def _show_start_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, timer_label: str) -> None:
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Start Quiz", callback_data=f"qs_tm_{chat_id}_start")]])
    await _setup_edit(ctx, chat_id, f"⏱ <b>Timer set: {timer_label}</b>\n\nAll set! Press Start when ready.", kb)


async def _show_explanation_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, show explanation", callback_data=f"qs_ex_{chat_id}_yes"),
         InlineKeyboardButton("❌ No (default)", callback_data=f"qs_ex_{chat_id}_no")],
    ])
    await _setup_edit(
        ctx, chat_id,
        "\U0001F4A1 <b>Show explanation after each question?</b>\n\n"
        "If Yes, the explanation will be sent as a separate message after each poll closes.",
        kb,
    )


async def _show_anticheat_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Enable Anti-Cheat", callback_data=f"qs_ac_{chat_id}_yes"),
         InlineKeyboardButton("❌ No, Skip", callback_data=f"qs_ac_{chat_id}_no")],
    ])
    await _setup_edit(
        ctx, chat_id,
        "\U0001F6E1 <b>Anti-Cheat Detection?</b>\n\n"
        "<i>⚠️ Warning: Users found using a double/duplicate account to cheat will be auto-kicked "
        "from the group.\nFalse positives possible — enable only if needed.</i>",
        kb,
    )


async def _show_section_mode_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """If the quiz has sections, walk through configuring each one in turn."""
    ps = pending_quiz_settings.get(chat_id, {})
    sections = ps.get("quiz", {}).get("sections", [])
    if not sections:
        await _show_start_prompt(ctx, chat_id, f"{ps.get('timer_override') or ps.get('quiz', {}).get('timer', 30)}s")
        return

    sec_settings = ps.setdefault("section_settings", {})
    next_idx = next((i for i in range(len(sections)) if str(i) not in sec_settings), None)

    if next_idx is None:
        summary = "✅ <b>All sections configured!</b>\n\n"
        for i, sec in enumerate(sections):
            cfg = sec_settings.get(str(i), {})
            if cfg.get("skip"):
                summary += f"• {sec.get('name', '?')}: quiz defaults\n"
            else:
                mode = cfg.get("mode", "perpoll")
                t_lbl = f"{cfg.get('slot_minutes', '?')}min slot" if mode == "slot" else f"{cfg.get('timer', 'default')}s/poll"
                cm_lbl = cfg.get("correct_mark") or "global"
                neg_lbl = cfg.get("neg_mark") if cfg.get("neg_mark") is not None else "global"
                summary += f"• {sec.get('name', '?')}: {t_lbl}  +{cm_lbl}/-{neg_lbl}\n"
        await _setup_edit(
            ctx, chat_id, summary + "\nPress <b>▶️ Start</b> when ready!",
            InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Start Quiz", callback_data=f"qs_tm_{chat_id}_start")]]),
        )
        return

    sec = sections[next_idx]
    sec_name = sec.get("name", f"Section {sec['question_range'][0]}–{sec['question_range'][1]}")
    s, e = sec["question_range"]
    progress = f"Section {next_idx + 1} of {len(sections)}"

    await _setup_edit(
        ctx, chat_id,
        f"\U0001F4DA <b>{sec_name}</b>  ({progress})\nQ{s}–{e}  ({e - s} questions)\n\nChoose <b>timing mode</b> for this section:",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("⏱ Per-poll timer (Case 1)", callback_data=f"qs_sec_{chat_id}_{next_idx}_mode_perpoll"),
             InlineKeyboardButton("\U0001F550 Whole-section slot (Case 2)", callback_data=f"qs_sec_{chat_id}_{next_idx}_mode_slot")],
            [InlineKeyboardButton("⏭ Keep quiz defaults", callback_data=f"qs_sec_{chat_id}_{next_idx}_mode_skip")],
        ]),
    )


async def _show_sec_timer_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, sec_idx: int, mode: str) -> None:
    mode_lbl = "\U0001F550 Slot mode" if mode == "slot" else "⏱ Per-poll mode"
    if mode == "slot":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{m} min", callback_data=f"qs_sec_{chat_id}_{sec_idx}_slotmin_{m}") for m in (10, 15, 20)],
            [InlineKeyboardButton(f"{m} min", callback_data=f"qs_sec_{chat_id}_{sec_idx}_slotmin_{m}") for m in (25, 30, 45)],
            [InlineKeyboardButton("60 min", callback_data=f"qs_sec_{chat_id}_{sec_idx}_slotmin_60")],
        ])
        await _setup_edit(ctx, chat_id, f"✅ {mode_lbl} selected\n\n\U0001F550 <b>Total slot duration for this section?</b>", kb)
    else:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{t}s", callback_data=f"qs_sec_{chat_id}_{sec_idx}_sectm_{t}") for t in (10, 15, 20, 25, 30)],
            [InlineKeyboardButton("⏭ Quiz default", callback_data=f"qs_sec_{chat_id}_{sec_idx}_sectm_skip")],
        ])
        await _setup_edit(ctx, chat_id, f"✅ {mode_lbl} selected\n\n⏱ <b>Per-poll timer for this section?</b>", kb)


async def _show_sec_marks_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, sec_idx: int) -> None:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(str(n), callback_data=f"qs_sec_{chat_id}_{sec_idx}_seccm_{n}") for n in range(1, 6)],
        [InlineKeyboardButton("⏭ Use global", callback_data=f"qs_sec_{chat_id}_{sec_idx}_seccm_skip")],
    ])
    ps = pending_quiz_settings.get(chat_id, {})
    sec_cfg = ps.get("section_settings", {}).get(str(sec_idx), {})
    if sec_cfg.get("slot_minutes"):
        timer_lbl = f"{sec_cfg['slot_minutes']} min slot"
    elif sec_cfg.get("timer"):
        timer_lbl = f"{sec_cfg['timer']}s per poll"
    else:
        timer_lbl = "quiz default timer"
    await _setup_edit(ctx, chat_id, f"✅ Timer: {timer_lbl}\n\n✅ <b>Correct mark for this section?</b>", kb)


async def _show_sec_neg_prompt(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, sec_idx: int, cm: float) -> None:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1/4", callback_data=f"qs_sec_{chat_id}_{sec_idx}_secnm_0.25"),
         InlineKeyboardButton("1/3", callback_data=f"qs_sec_{chat_id}_{sec_idx}_secnm_0.333"),
         InlineKeyboardButton("1/2", callback_data=f"qs_sec_{chat_id}_{sec_idx}_secnm_0.5"),
         InlineKeyboardButton("1", callback_data=f"qs_sec_{chat_id}_{sec_idx}_secnm_1.0")],
        [InlineKeyboardButton("0 (no neg)", callback_data=f"qs_sec_{chat_id}_{sec_idx}_secnm_0"),
         InlineKeyboardButton("⏭ Use global", callback_data=f"qs_sec_{chat_id}_{sec_idx}_secnm_skip")],
    ])
    await _setup_edit(ctx, chat_id, f"✅ Correct mark: {cm}\n\n➖ <b>Negative mark for this section?</b>", kb)


async def quiz_setup_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle every `qs_`-prefixed quiz-setup button press."""
    try:
        query = update.callback_query
        data = query.data
        parts = data.split("_")
        if not parts or parts[0] != "qs":
            await query.answer()
            return

        step = parts[1]

        # Anonymous-admin identity verification: qs_anon_verify_{chat_id}_{qid}
        if step == "anon" and len(parts) >= 5 and parts[2] == "verify":
            await _handle_anon_verify(query, ctx, parts)
            return

        chat_id = int(parts[2])
        value = parts[3]

        if chat_id not in pending_quiz_settings:
            await query.edit_message_text("❌ Session expired. Start again.")
            return

        ps = pending_quiz_settings[chat_id]
        if query.from_user.id != ps.get("initiator_id"):
            await query.answer("❌ Only the quiz initiator can configure this.", show_alert=True)
            return

        if step == "cm":
            ps["correct_mark"] = 1.0 if value == "skip" else float(value)
            await query.edit_message_text(f"✅ Correct mark: {ps['correct_mark']}")
            await _show_neg_mark_prompt(ctx, chat_id, ps["correct_mark"])

        elif step == "nm":
            ps["neg_mark"] = 0.0 if value == "skip" else round(float(value) * ps["correct_mark"], 4)
            await query.edit_message_text(f"✅ Negative mark: {ps['neg_mark']}")
            await _show_shuffle_prompt(ctx, chat_id)

        elif step == "sh":
            ps["shuffle_q"] = value in ("q", "b")
            ps["shuffle_o"] = value in ("o", "b")
            label = {"q": "Questions", "o": "Options", "b": "Both", "skip": "None"}.get(value, "None")
            await query.edit_message_text(f"✅ Shuffle: {label}")
            if ps["shuffle_o"]:
                await _show_shuffle_count_prompt(ctx, chat_id)
            else:
                ps["shuffle_o_count"] = 0
                await _show_explanation_prompt(ctx, chat_id)

        elif step == "shc":
            ps["shuffle_o_count"] = 0 if value == "all" else int(value)
            label = "All" if value == "all" else f"First {value}"
            await query.edit_message_text(f"✅ Options shuffle range: {label}")
            await _show_explanation_prompt(ctx, chat_id)

        elif step == "ex":
            ps["show_explanation"] = value == "yes"
            await query.edit_message_text(f"✅ Show explanation: {'Yes ✅' if ps['show_explanation'] else 'No ❌'}")
            if ps.get("chat_type") in ("group", "supergroup"):
                await _show_anticheat_prompt(ctx, chat_id)
            else:
                ps["anti_cheat"] = False
                await _show_timer_prompt(ctx, chat_id)

        elif step == "ac":
            ps["anti_cheat"] = value == "yes"
            await query.edit_message_text(f"\U0001F6E1 Anti-Cheat: {'✅ Enabled' if ps['anti_cheat'] else '❌ Disabled'}")
            await _show_timer_prompt(ctx, chat_id)

        elif step == "sec":
            await _handle_sec_callback(query, ctx, chat_id, ps, parts)

        elif step == "qs":
            prev = await _get_quiz_prefs(chat_id)
            for key in ("correct_mark", "neg_mark", "shuffle_q", "shuffle_o", "shuffle_o_count", "show_explanation", "timer_override", "anti_cheat"):
                ps[key] = prev[key]
            await query.edit_message_text("⚡ <b>Quick Start!</b> Launching with your last-used settings...", parse_mode=ParseMode.HTML)
            await _launch_quiz_from_settings(chat_id, ctx, ps)
            del pending_quiz_settings[chat_id]

        elif step == "tm":
            if value == "start":
                await query.edit_message_text("\U0001F680 Starting quiz...")
                await _launch_quiz_from_settings(chat_id, ctx, ps)
                del pending_quiz_settings[chat_id]
            elif value == "default":
                ps["timer_override"] = None
                await query.edit_message_text("✅ Timer: quiz default")
                await _show_section_mode_prompt(ctx, chat_id)
            else:
                ps["timer_override"] = int(value)
                await query.edit_message_text(f"✅ Timer: {value}s")
                await _show_section_mode_prompt(ctx, chat_id)
    except Exception as e:
        logger.error("quiz_setup_callback error: %s", e, exc_info=True)


async def _handle_sec_callback(query, ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, ps: dict, parts: list[str]) -> None:
    # qs_sec_{chat_id}_{sec_idx}_{substep}_{value}
    if len(parts) < 6:
        await query.answer("❌ Bad data")
        return
    await query.answer()
    sec_idx = int(parts[3])
    substep = parts[4]
    val = parts[5]
    sec_cfg = ps.setdefault("section_settings", {}).setdefault(str(sec_idx), {})

    if substep == "mode":
        if val == "skip":
            sec_cfg["mode"] = "perpoll"
            sec_cfg["skip"] = True
            await _show_section_mode_prompt(ctx, chat_id)
        elif val == "slot":
            sec_cfg["mode"] = "slot"
            await _show_sec_timer_prompt(ctx, chat_id, sec_idx, "slot")
        else:
            sec_cfg["mode"] = "perpoll"
            await _show_sec_timer_prompt(ctx, chat_id, sec_idx, "perpoll")
    elif substep == "slotmin":
        sec_cfg["slot_minutes"] = int(val)
        await _show_sec_marks_prompt(ctx, chat_id, sec_idx)
    elif substep == "sectm":
        sec_cfg["timer"] = None if val == "skip" else int(val)
        await _show_sec_marks_prompt(ctx, chat_id, sec_idx)
    elif substep == "seccm":
        sec_cfg["correct_mark"] = None if val == "skip" else float(val)
        cm_for_neg = sec_cfg.get("correct_mark") or ps.get("correct_mark", 1)
        await _show_sec_neg_prompt(ctx, chat_id, sec_idx, cm_for_neg)
    elif substep == "secnm":
        if val == "skip":
            sec_cfg["neg_mark"] = None
        elif val == "0":
            sec_cfg["neg_mark"] = 0.0
        else:
            cm = sec_cfg.get("correct_mark") or ps.get("correct_mark", 1)
            sec_cfg["neg_mark"] = round(float(val) * cm, 4)
        await _show_section_mode_prompt(ctx, chat_id)


async def _handle_anon_verify(query, ctx: ContextTypes.DEFAULT_TYPE, parts: list[str]) -> None:
    """Anonymous group admins arrive with a fake sender id; this callback
    confirms their real identity (query.from_user.id) and resumes /start."""
    from quizbot.database import QuizRepository

    await query.answer("✅ Identity confirmed!")
    real_user_id = query.from_user.id
    anon_chat_id = int(parts[3])
    anon_qid = "_".join(parts[4:])
    await query.edit_message_text("✅ <b>Identity confirmed!</b> Starting quiz setup...", parse_mode=ParseMode.HTML)

    if not await is_premium_user(real_user_id):
        await safe_send_message(ctx, anon_chat_id, "Please help us to make this project more valuable by purchasing premium! Thanks")
        return
    if not await rate_limiter.check(real_user_id):
        await safe_send_message(ctx, anon_chat_id, "⏱️ Too many requests. Wait a moment.")
        return
    if not anon_qid:
        return
    if session_mgr.get(anon_chat_id):
        await safe_send_message(ctx, anon_chat_id, "⚠️ A quiz is already running. /stop it first.")
        return

    quiz_repo = QuizRepository(get_db())
    quiz = await quiz_repo.get(anon_qid)
    if not quiz:
        await safe_send_message(ctx, anon_chat_id, "❌ Invalid QuestionSetID.")
        return

    allowed, batch = await resolve_quiz_access(anon_qid, quiz, anon_chat_id, "group", real_user_id, ctx=ctx)
    if not allowed:
        if batch:
            msg = f"\U0001F512 <b>Paid Quiz — Access Required</b>\n\n\U0001F4E6 Batch: <b>{batch.get('name', '')}</b>\n"
            if batch.get("payment_link"):
                msg += f"\n\U0001F4B3 <b>Pay here:</b> {batch['payment_link']}\n"
            await safe_send_message(ctx, anon_chat_id, msg, parse_mode=ParseMode.HTML)
        else:
            await safe_send_message(ctx, anon_chat_id, f"❌ Contact creator ID {quiz.get('creator_id')} for access.")
        return

    quiz["question_set_id"] = quiz["qid"]
    quiz["negative_marking"] = quiz.get("negative_marks", 0)
    quiz["correct_mark"] = quiz.get("correct_marks", 1)

    # Content protection defaults to ON here too (anon-admin path is always
    # in a group); only lifted if the group itself is the quiz's own creator
    # account, matching the original's `protect = True; if anon_chat_id ==
    # creator_id: protect = False`.
    pending_quiz_settings[anon_chat_id] = {
        "quiz": quiz, "update": query, "skip": 0,
        "protect": anon_chat_id != quiz.get("creator_id"), "chat_type": "group",
        "correct_mark": 1.0, "neg_mark": 0.0,
        "shuffle_q": False, "shuffle_o": False, "show_explanation": False,
        "timer_override": None, "initiator_id": real_user_id,
    }
    await show_correct_mark_prompt(ctx, anon_chat_id)


async def _launch_quiz_from_settings(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE, ps: dict) -> None:
    """Apply the collected wizard settings to the quiz and start it."""
    from .quiz_play import run_group_quiz, start_private_quiz

    try:
        quiz = ps["quiz"]
        update = ps["update"]
        skip = ps.get("skip", 0)
        protect = ps.get("protect", False)
        chat_type = ps.get("chat_type", "group")
        qset_id = quiz["question_set_id"]

        if ps.get("timer_override"):
            quiz["timer"] = ps["timer_override"]
        quiz["shuffle"] = ps.get("shuffle_q", False)
        quiz["shuffle_options"] = ps.get("shuffle_o", False)
        quiz["shuffle_options_count"] = ps.get("shuffle_o_count", 0)
        quiz["negative_marking"] = ps.get("neg_mark", 0)
        quiz["correct_mark"] = ps.get("correct_mark", 1)
        quiz["show_explanation"] = ps.get("show_explanation", False)
        quiz["anti_cheat"] = ps.get("anti_cheat", False)

        tasks.spawn(
            _save_quiz_prefs(chat_id, {
                "correct_mark": quiz["correct_mark"], "neg_mark": quiz["negative_marking"],
                "shuffle_q": quiz["shuffle"], "shuffle_o": quiz["shuffle_options"],
                "shuffle_o_count": quiz["shuffle_options_count"], "show_explanation": quiz["show_explanation"],
                "anti_cheat": quiz["anti_cheat"], "timer_override": ps.get("timer_override"),
            }),
            name=f"save_quiz_prefs_{chat_id}",
        )

        sec_settings = ps.get("section_settings", {})
        for i, sec in enumerate(quiz.get("sections", [])):
            cfg = sec_settings.get(str(i), {})
            if cfg.get("skip"):
                continue
            if cfg.get("mode"):
                sec["mode"] = cfg["mode"]
            if cfg.get("slot_minutes"):
                sec["slot_minutes"] = cfg["slot_minutes"]
            if cfg.get("timer") is not None:
                sec["timer"] = cfg["timer"]
            if cfg.get("correct_mark") is not None:
                sec["correct_mark"] = cfg["correct_mark"]
            if cfg.get("neg_mark") is not None:
                sec["neg_mark"] = cfg["neg_mark"]

        await _send_start_card(ctx, chat_id, quiz, skip, chat_type)
        await asyncio.sleep(0.5)

        if chat_type == "private":
            await start_private_quiz(chat_id, ctx, quiz["questions"], quiz, qset_id, skip)
            return

        questions = quiz["questions"]
        if quiz.get("shuffle") and not quiz.get("sections"):
            random.shuffle(questions)

        thread_id = None
        try:
            msg_obj = update.message if hasattr(update, "message") else getattr(update, "effective_message", None)
            if msg_obj and msg_obj.message_thread_id:
                thread_id = msg_obj.message_thread_id
        except Exception:
            pass

        session_data = {
            "quiz_id": qset_id, "current_index": skip, "paused": False, "polls": {},
            "participants": {}, "is_private": False, "section_msgs": [],
            "modified_timer_offset": 0, "message_thread_id": thread_id,
            "quiz_data": quiz, "anti_cheat": ps.get("anti_cheat", False),
        }
        await session_mgr.create(chat_id, session_data)
        tasks.spawn(run_group_quiz(chat_id, ctx, questions, quiz, protect, update, skip), name=f"quiz_{chat_id}_main")
    except Exception as e:
        logger.error("_launch_quiz_from_settings error: %s", e, exc_info=True)
        await safe_send_message(ctx, chat_id, "❌ Error launching quiz.")


async def _send_start_card(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, quiz: dict, skip: int, chat_type: str) -> None:
    total_q = len(quiz["questions"])
    timer = quiz["timer"]
    neg = quiz.get("negative_marking", 0)
    cm = quiz.get("correct_mark", 1)
    sections = quiz.get("sections", [])
    has_multi = any(
        isinstance(q.get("correct_option_id"), list) and len(q["correct_option_id"]) > 1 for q in quiz["questions"]
    )
    shuffle_q = "✅" if quiz.get("shuffle") else "❌"
    shuffle_o = "✅" if quiz.get("shuffle_options") else "❌"
    neg_str = f"-{neg}" if neg else "None"

    card = f"\U0001F3AF <b>{quiz.get('quiz_name', 'Quiz')}</b>\n{'─' * 30}\n\U0001F4CB <b>Questions:</b> {total_q}"
    if skip:
        card += f" <i>(starting from Q{skip + 1})</i>"
    card += f"\n⏱ <b>Timer:</b> {timer}s per question"
    if sections:
        card += f"\n\U0001F4C2 <b>Sections:</b> {len(sections)}"
        for sec in sections:
            r = sec.get("question_range", (0, 0))
            card += f"\n   • {sec.get('name', '?')} — Q{r[0]}–{r[1]} ({sec.get('timer', timer)}s)"
    card += (
        f"\n✅ <b>Correct mark:</b> +{cm}\n➖ <b>Negative:</b> {neg_str}\n"
        f"\U0001F500 <b>Shuffle Q:</b> {shuffle_q}  |  <b>Options:</b> {shuffle_o}\n"
        f"\U0001F4A1 <b>Show explanation:</b> {'✅ Yes' if quiz.get('show_explanation') else '❌ No'}"
    )
    if chat_type in ("group", "supergroup"):
        card += f"\n\U0001F6E1 <b>Anti-Cheat:</b> {'✅ On' if quiz.get('anti_cheat') else '❌ Off'}"
    if has_multi:
        card += "\n\U0001F522 <b>Multi-correct</b> questions included"
    if quiz.get("promo_message"):
        card += "\n\U0001F4E2 <i>Promo messages enabled</i>"
    card += f"\n{'─' * 30}\n\U0001F680 <b>Starting now — good luck!</b>"

    await safe_send_message(ctx, chat_id, card, parse_mode=ParseMode.HTML)


def register(application: Application) -> None:
    application.add_handler(CallbackQueryHandler(quiz_setup_callback, pattern="^qs_"))
