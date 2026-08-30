"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import fractions
import logging
from io import BytesIO

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from quizbot.database import QuizRepository, get_db
from quizbot.shared import config
from quizbot.shared.utils import is_premium_user

from .. import state
from ..keyboards import quiz_editor_main_kb, quiz_editor_qmgr_kb, quiz_editor_settings_kb
from ..ratelimit import ratelimit

logger = logging.getLogger(__name__)

QUESTIONS_PER_PAGE = config.QUESTIONS_PER_PAGE


def _can_edit(quiz: dict, user_id: int) -> bool:
    if not quiz:
        return False
    if quiz.get("creator_id") == user_id:
        return True
    if user_id == config.OWNER_ID or user_id in config.ADMIN_IDS:
        return True
    return user_id in (quiz.get("edit_permissions") or [])


def _quiz_info_text(quiz: dict) -> str:
    question_count = len(quiz.get("questions", []))
    section_count = len(quiz.get("sections", []))
    section_suffix = f" ({section_count} sections)" if section_count else ""
    promo_flag = "Set" if quiz.get("promo_message") else "None"
    return (
        f"🏷️ **Name:** {quiz.get('quiz_name', 'N/A')[:50]}\n"
        f"❓ **Questions:** {question_count}{section_suffix}\n"
        f"⏱️ **Timer:** {quiz.get('timer', 'N/A')}s\n"
        f"🏷️ **Type:** {quiz.get('quiz_type', 'free').title()}\n"
        f"➖ **Negative marking:** {quiz.get('negative_marks', 0)}\n"
        f"📢 **Promo:** {promo_flag}"
    )


@ratelimit("strict")
async def edit_cmd(c: Client, m: Message) -> None:
    """/edit <quiz_id> -- open the inline quiz editor."""
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("🔒 Premium required: /pay")
        return
    args = m.text.split()
    if len(args) < 2:
        await m.reply("Usage: `/edit <quiz_id>`")
        return
    qid = args[1]
    quiz = await QuizRepository(get_db()).get(qid)
    if not quiz:
        await m.reply("⚠️ Not found.")
        return
    if not _can_edit(quiz, uid):
        await m.reply("🔐 No permission to edit this quiz.")
        return
    state.edit_sessions[uid] = {"qid": qid, "page": 0, "field": None}
    await m.reply(f"✍️ **Quiz Editor**\n\n{_quiz_info_text(quiz)}", reply_markup=quiz_editor_main_kb(qid))


@ratelimit("default")
async def stopedit_cmd(c: Client, m: Message) -> None:
    """/stopedit -- end the active /edit session."""
    uid = m.from_user.id
    if uid in state.edit_sessions:
        state.edit_sessions.pop(uid, None)
        await m.reply("✅ Editor session stopped.")
    else:
        await m.reply("⚠️ No active edit session.")


async def _show_questions_page(cb: CallbackQuery, qid: str, page: int) -> None:
    quiz = await QuizRepository(get_db()).get(qid)
    questions = quiz.get("questions", []) if quiz else []
    if not questions:
        await cb.message.edit_text("⚠️ No questions.")
        return
    total_pages = (len(questions) + QUESTIONS_PER_PAGE - 1) // QUESTIONS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    start = page * QUESTIONS_PER_PAGE
    end = min(start + QUESTIONS_PER_PAGE, len(questions))

    text = f"❓ **Questions** (Page {page + 1}/{total_pages})\n\n"
    buttons = []
    for i in range(start, end):
        q = questions[i]
        q_text = q.get("question", "")[:40] + ("..." if len(q.get("question", "")) > 40 else "")
        text += f"**{i + 1}.** {q_text}\n"
        for j, opt in enumerate(q.get("options", [])):
            marker = "[correct]" if j == q.get("correct_option_id", 0) else "        "
            text += f"   {marker} {opt[:30]}{'...' if len(opt) > 30 else ''}\n"
        if q.get("explanation"):
            text += f"   Explanation: {q['explanation'][:25]}...\n"
        text += "\n"
        buttons.append([InlineKeyboardButton(f"✍️ Edit Q{i + 1}", callback_data=f"eq_{i}_{page}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"prev_{qid}_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️ Next", callback_data=f"next_{qid}_{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data=f"qmgr_{qid}")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))


def _question_edit_view(qid: str, questions: list[dict], idx: int) -> tuple[str, InlineKeyboardMarkup]:
    q = questions[idx]
    page = idx // QUESTIONS_PER_PAGE
    text = f"✍️ **Edit Q{idx + 1}/{len(questions)}**\n\n**Q:** {q.get('question', 'N/A')}\n\n"
    for i, opt in enumerate(q.get("options", [])):
        marker = "[correct]" if i == q.get("correct_option_id", 0) else "[ ]"
        text += f"{marker} {opt}\n"
    if q.get("explanation"):
        text += f"\n**Explanation:** {q['explanation']}\n"

    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"eq_{idx - 1}_{page}"))
    if idx < len(questions) - 1:
        nav.append(InlineKeyboardButton("▶️ Next", callback_data=f"eq_{idx + 1}_{page}"))
    buttons = [
        [InlineKeyboardButton("🔁 Replace", callback_data=f"replace_{idx}_{page}")],
        [InlineKeyboardButton("🗑️ Delete", callback_data=f"delq_{idx}_{page}")],
    ]
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data=f"view_{qid}_{page}")])
    return text, InlineKeyboardMarkup(buttons)


async def _show_question_edit(cb: CallbackQuery, qid: str, idx: int) -> None:
    quiz = await QuizRepository(get_db()).get(qid)
    questions = quiz.get("questions", []) if quiz else []
    if idx < 0 or idx >= len(questions):
        await cb.answer("⚠️ Not found", show_alert=True)
        return
    text, kb = _question_edit_view(qid, questions, idx)
    await cb.message.edit_text(text, reply_markup=kb)


async def _replace_question(m: Message, uid: int, qid: str, idx: int, text: str) -> None:
    from ..parsing import parse_question_block

    parsed = parse_question_block(text)
    if not parsed or isinstance(parsed["correct_option_id"], list):
        await m.reply(
            "⚠️ Invalid format.\n\nFormat:\nQuestion\nOpt1\nOpt2 (correct one marked with a check emoji)\nOpt3\nEx: Explanation"
        )
        return
    repo = QuizRepository(get_db())
    quiz = await repo.get(qid)
    questions = quiz["questions"]
    if idx >= len(questions):
        await m.reply("⚠️ Question no longer exists.")
        return
    questions[idx] = {
        "question": parsed["question"],
        "options": parsed["options"],
        "correct_option_id": parsed["correct_option_id"],
        "explanation": parsed.get("explanation"),
        "file_id": None,
        "reply_text": None,
    }
    await repo.update_field(qid, "questions", questions)
    state.edit_sessions[uid]["field"] = None
    text_view, kb_view = _question_edit_view(qid, questions, idx)
    await m.reply(f"✅ Q{idx + 1} replaced.\n\n{text_view}", reply_markup=kb_view)


async def _delete_question(cb: CallbackQuery, qid: str, idx: int, page: int) -> None:
    repo = QuizRepository(get_db())
    quiz = await repo.get(qid)
    questions = quiz.get("questions", []) if quiz else []
    if idx >= len(questions):
        await cb.answer("⚠️ Not found", show_alert=True)
        return
    questions.pop(idx)
    await repo.update_field(qid, "questions", questions)
    await cb.answer("🗑️ Deleted")
    total_pages = (len(questions) + QUESTIONS_PER_PAGE - 1) // QUESTIONS_PER_PAGE if questions else 1
    await _show_questions_page(cb, qid, min(page, max(0, total_pages - 1)))


async def _delete_range(m: Message, uid: int, qid: str, text: str) -> None:
    if "-" not in text:
        await m.reply("⚠️ Invalid format. Use: 1-5 or 10-20")
        return
    parts = text.split("-")
    if len(parts) != 2:
        await m.reply("⚠️ Invalid format. Use: 1-5 or 10-20")
        return
    try:
        start, end = int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        await m.reply("⚠️ Invalid numbers. Use format: 1-5 or 10-20")
        return
    if start < 1 or end < 1:
        await m.reply("⚠️ Question numbers start from 1.")
        return
    if start > end:
        await m.reply("⚠️ Start must be <= end.")
        return

    quiz = await QuizRepository(get_db()).get(qid)
    if not quiz:
        await m.reply("⚠️ Quiz not found.")
        return
    total = len(quiz.get("questions", []))
    if start > total or end > total:
        await m.reply(f"⚠️ Quiz only has {total} questions. You tried to delete Q{start}-Q{end}.")
        return

    start_idx, end_idx = start - 1, end - 1
    delete_count = end_idx - start_idx + 1
    state.edit_sessions[uid]["pending_delete"] = {"start": start_idx, "end": end_idx, "count": delete_count}
    state.edit_sessions[uid]["field"] = "confirm_delete"
    await m.reply(
        f"⚠️ **Confirm deletion**\n\n"
        f"Delete questions **{start}** to **{end}** ({delete_count} questions, "
        f"{total - delete_count} would remain).\n\n"
        f"Type `YES` to confirm or anything else to cancel."
    )


async def _update_field(m: Message, uid: int, qid: str, field: str, value: str) -> bool:
    try:
        if field == "timer":
            value = int(value)
            if value <= 10:
                raise ValueError("Timer must be > 10")
        elif field == "quiz_type":
            value = value.lower()
            if value not in ("free", "paid"):
                raise ValueError("Type must be free/paid")
        elif field == "negative_marks":
            value = float(fractions.Fraction(value)) if "/" in value else float(value)
            if not (0 <= value < 1):
                raise ValueError("Negative marking must be 0-0.99")
        await QuizRepository(get_db()).update_field(qid, field, value)
        await m.reply("✅ Updated.")
        return True
    except Exception as exc:
        await m.reply(f"⚠️ Error: {exc}")
        return False


async def _add_questions(m: Message, uid: int, qid: str, text: str) -> None:
    from ..parsing import parse_question_block

    repo = QuizRepository(get_db())
    quiz = await repo.get(qid)
    questions = quiz.get("questions", [])
    current_count = len(questions)
    new_questions = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        parsed = parse_question_block(block)
        if not parsed:
            continue
        new_questions.append(
            {
                "question": parsed["question"],
                "options": parsed["options"],
                "correct_option_id": parsed["correct_option_id"],
                "explanation": parsed.get("explanation"),
                "file_id": None,
                "reply_text": None,
            }
        )
    if not new_questions:
        await m.reply("⚠️ No valid questions found.")
        return
    if current_count + len(new_questions) > 500:
        await m.reply("⚠️ Max 500 questions per quiz.")
        return
    questions.extend(new_questions)
    await repo.update_field(qid, "questions", questions)
    await m.reply(f"✅ {len(new_questions)} added. Total: {current_count + len(new_questions)}")
    state.edit_sessions[uid]["field"] = None


async def _export_quiz(cb: CallbackQuery, quiz: dict) -> None:
    lines = []
    for q in quiz.get("questions", []):
        lines.append(q.get("question", "N/A"))
        for j, opt in enumerate(q.get("options", [])):
            suffix = " [correct]" if j == q.get("correct_option_id", 0) else ""
            lines.append(f"{opt}{suffix}")
        if q.get("explanation"):
            lines.append(f"Ex: {q['explanation']}")
        if q.get("reply_text"):
            lines.append(f"RT: <ggn>{q['reply_text']}</ggn>")
        if q.get("file_id"):
            lines.append(f"ID: {q['file_id']}")
        lines.append("")
    content = "\n".join(lines).rstrip()
    filename = f"quiz_{quiz.get('qid', 'x')}.txt"
    buf = BytesIO(content.encode("utf-8"))
    buf.name = filename
    try:
        await cb.message.reply_document(
            document=buf, file_name=filename,
            caption=f"📤 Exported ({len(quiz.get('questions', []))} questions)",
        )
        await cb.answer("📤 Exported")
    except Exception as exc:
        await cb.answer(f"⚠️ Error: {exc}", show_alert=True)


async def _show_shuffle(cb: CallbackQuery, quiz: dict) -> None:
    qid = quiz.get("qid")
    shuffle_q = bool(quiz.get("shuffle_questions", False))
    shuffle_o = bool(quiz.get("shuffle_options", False))
    has_sections = bool(quiz.get("sections", []))
    buttons = []
    if not has_sections:
        buttons.append([InlineKeyboardButton(f"❓ Questions: {'ON' if shuffle_q else 'OFF'}", callback_data=f"tshufq_{qid}")])
    buttons.append([InlineKeyboardButton(f"🔤 Options: {'ON' if shuffle_o else 'OFF'}", callback_data=f"tshufo_{qid}")])
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data=f"main_{qid}")])
    text = f"🔀 **Shuffle**\n\nQuestions: {'ON' if shuffle_q else 'OFF'}\nOptions: {'ON' if shuffle_o else 'OFF'}"
    if has_sections:
        text += "\n\n⚠️ Question shuffle is disabled while sections are set."
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def _show_permissions(cb: CallbackQuery, quiz: dict, app: Client) -> None:
    perms = quiz.get("edit_permissions", [])
    qid = quiz.get("qid")
    text = "🔐 **Edit Permissions**\n\n"
    if perms:
        text += "**Editors:**\n"
        for uid in perms[:5]:
            try:
                u = await app.get_users(uid)
                text += f"- {u.first_name[:20]} (@{u.username or 'N/A'})\n"
            except Exception:
                text += f"- ID: {uid}\n"
        if len(perms) > 5:
            text += f"... +{len(perms) - 5}\n"
    else:
        text += "No editors.\n"
    text += "\nUsage: send a user ID after tapping Add or Remove."
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Add", callback_data=f"addperm_{qid}")],
            [InlineKeyboardButton("➖ Remove", callback_data=f"remperm_{qid}")],
            [InlineKeyboardButton("◀️ Back", callback_data=f"main_{qid}")],
        ]
    )
    await cb.message.edit_text(text, reply_markup=kb)


async def _add_permission(m: Message, app: Client, uid: int, qid: str, text: str) -> None:
    try:
        target_uid = int(text)
    except ValueError:
        await m.reply("⚠️ Invalid ID.")
        return
    try:
        user = await app.get_users(target_uid)
    except Exception:
        await m.reply("⚠️ User not found.")
        return
    repo = QuizRepository(get_db())
    quiz = await repo.get(qid)
    perms = quiz.get("edit_permissions", [])
    if target_uid not in perms:
        perms.append(target_uid)
    await repo.update_field(qid, "edit_permissions", perms)
    await m.reply(f"✅ {user.first_name} added as editor.")
    state.edit_sessions[uid]["field"] = None


async def _remove_permission(m: Message, uid: int, qid: str, text: str) -> None:
    try:
        target_uid = int(text)
    except ValueError:
        await m.reply("⚠️ Invalid ID.")
        return
    repo = QuizRepository(get_db())
    quiz = await repo.get(qid)
    perms = quiz.get("edit_permissions", [])
    if target_uid in perms:
        perms.remove(target_uid)
    await repo.update_field(qid, "edit_permissions", perms)
    await m.reply("✅ Removed.")
    state.edit_sessions[uid]["field"] = None


_FIELD_MAP = {"ename": "quiz_name", "etimer": "timer", "etype": "quiz_type", "eneg": "negative_marks"}
_FIELD_PROMPTS = {
    "quiz_name": "🏷️ New name:",
    "timer": "⏱️ New timer in seconds (>10):",
    "quiz_type": "🏷️ New type (free/paid):",
    "negative_marks": "➖ New negative marking (0-0.99):",
}


async def edit_tree_cb(c: Client, cb: CallbackQuery) -> None:
    """Every callback in the /edit tree except settings (`stg_`), payments
    (`plan_`/`pay_`/`buy_`), quick-save (`qd_`), search (`srch_`), batches
    (`bat_`), and quiz-list pagination (`prev:`/`next:`/`refresh:`) --
    those are routed to their own handler modules."""
    uid = cb.from_user.id
    data = cb.data
    if data == "page_info":
        await cb.answer()
        return
    if uid not in state.edit_sessions:
        await cb.answer()
        return
    qid = state.edit_sessions[uid]["qid"]
    quiz = await QuizRepository(get_db()).get(qid)
    if not quiz:
        await cb.answer("⚠️ Not found", show_alert=True)
        return

    try:
        if data.startswith("main_"):
            await cb.message.edit_text(f"✍️ **Quiz Editor**\n\n{_quiz_info_text(quiz)}", reply_markup=quiz_editor_main_kb(qid))
        elif data.startswith("set_"):
            await cb.message.edit_text("⚙️ **Settings**", reply_markup=quiz_editor_settings_kb(qid))
        elif data.startswith("qmgr_"):
            await cb.message.edit_text("❓ **Question Management**", reply_markup=quiz_editor_qmgr_kb(qid))
        elif data.startswith("view_"):
            parts = data.split("_")
            page = int(parts[2]) if len(parts) > 2 else 0
            await _show_questions_page(cb, qid, page)
        elif data.startswith(("next_", "prev_")):
            parts = data.split("_")
            page = int(parts[2]) if len(parts) > 2 else 0
            await _show_questions_page(cb, qid, page)
        elif data.startswith("eq_"):
            parts = data.split("_")
            await _show_question_edit(cb, qid, int(parts[1]))
        elif data.startswith("replace_"):
            parts = data.split("_")
            state.edit_sessions[uid].update(
                {"field": "replace_question", "q_idx": int(parts[1]), "page": int(parts[2]) if len(parts) > 2 else 0}
            )
            await cb.message.edit_text(
                "🔁 **Replace Question**\n\nFormat:\nQuestion\nOpt1\nOpt2 (mark correct with a check emoji)\nOpt3\nEx: Explanation"
            )
        elif data.startswith("delq_"):
            parts = data.split("_")
            await _delete_question(cb, qid, int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
        elif data.startswith("delrange_"):
            state.edit_sessions[uid]["field"] = "delete_range"
            await cb.message.edit_text(
                "🗑️ **Delete Questions Range**\n\nEnter a range, e.g. `1-5` or `10-20`."
            )
        elif data.startswith(("ename_", "etimer_", "etype_", "eneg_")):
            key = data.split("_")[0]
            field = _FIELD_MAP[key]
            state.edit_sessions[uid]["field"] = field
            await cb.message.edit_text(_FIELD_PROMPTS[field])
        elif data.startswith("add_"):
            state.edit_sessions[uid]["field"] = "add_questions"
            await cb.message.edit_text(
                "➕ **Add Questions**\n\nFormat:\nQuestion\nOpt1\nOpt2 (mark correct with a check emoji)\nOpt3\n"
                "Ex: Explanation\n\nSeparate multiple questions with a blank line."
            )
        elif data.startswith("exp_"):
            await _export_quiz(cb, quiz)
        elif data.startswith("shuf_"):
            await _show_shuffle(cb, quiz)
        elif data.startswith(("tshufq_", "tshufo_")):
            field = "shuffle_questions" if "tshufq" in data else "shuffle_options"
            new_value = 0 if quiz.get(field, False) else 1
            await QuizRepository(get_db()).update_field(qid, field, new_value)
            refreshed = await QuizRepository(get_db()).get(qid)
            await _show_shuffle(cb, refreshed)
        elif data.startswith("perms_"):
            await _show_permissions(cb, quiz, c)
        elif data.startswith("addperm_"):
            state.edit_sessions[uid]["field"] = "add_perm"
            await cb.message.edit_text("➕ **Add Editor**\n\nSend the user's Telegram ID:")
        elif data.startswith("remperm_"):
            state.edit_sessions[uid]["field"] = "rem_perm"
            await cb.message.edit_text("➖ **Remove Editor**\n\nSend the user's Telegram ID:")
        elif data.startswith("epromo_"):
            state.edit_sessions[uid]["field"] = "promo_message"
            await cb.message.edit_text(
                "📢 **Edit Promo Message**\n\nSend the new promo text.\nSend `skip` or `no` to remove it."
            )
        elif data.startswith("close_"):
            await cb.message.edit_text("✖️ Closed.")
            state.edit_sessions.pop(uid, None)
        await cb.answer()
    except Exception as exc:
        logger.exception("edit_tree_cb failed for data=%s", data)
        await cb.answer(f"⚠️ Error: {str(exc)[:50]}", show_alert=True)


def in_edit_session_filter():
    async def func(_, __, m: Message) -> bool:
        if not m.from_user:
            return False
        uid = m.from_user.id
        if uid not in state.edit_sessions:
            return False
        session = state.edit_sessions[uid]
        return bool(session.get("field") or session.get("stg_field"))

    return filters.create(func)


async def handle_edit_text_input(c: Client, m: Message) -> None:
    """Free-text input while an /edit field or a creator-settings field is
    awaiting a value. Settings input (`stg_field`) is delegated to
    handlers/settings.py so its logic stays in one place."""
    uid = m.from_user.id
    session = state.edit_sessions.get(uid, {})

    if session.get("stg_field"):
        from .settings import _show_settings
        from quizbot.database import CreatorSettingsRepository

        stg_field = session["stg_field"]
        text_in = m.text.strip()
        settings_repo = CreatorSettingsRepository(get_db())
        if stg_field == "default_text":
            value = None if text_in.lower() in ("none", "clear", "no") else text_in
            await settings_repo.update(uid, default_text=value)
            session.pop("stg_field", None)
            await m.reply(f"✅ Default text {'cleared' if value is None else 'saved'}!")
            await _show_settings(uid, m, edit=False)
        elif stg_field == "qd_promo":
            s = await settings_repo.get(uid)
            qd = s.get("quiz_defaults") or {}
            qd["promo"] = None if text_in.lower() in ("none", "clear", "no") else text_in
            await settings_repo.update(uid, quiz_defaults=qd)
            session.pop("stg_field", None)
            await m.reply("✅ Quick-save promo updated!")
        return

    if not session.get("field"):
        return
    qid, field, text = session["qid"], session["field"], m.text.strip()

    try:
        if field in ("quiz_name", "timer", "quiz_type", "negative_marks"):
            if await _update_field(m, uid, qid, field, text):
                session["field"] = None
        elif field == "add_questions":
            await _add_questions(m, uid, qid, text)
        elif field == "replace_question":
            await _replace_question(m, uid, qid, session.get("q_idx", 0), text)
        elif field == "delete_range":
            await _delete_range(m, uid, qid, text)
        elif field == "confirm_delete":
            if text.upper() == "YES":
                pending = session.get("pending_delete", {})
                start_idx, end_idx = pending.get("start", 0), pending.get("end", 0)
                delete_count = pending.get("count", 0)
                repo = QuizRepository(get_db())
                quiz = await repo.get(qid)
                questions = quiz.get("questions", [])
                for i in range(end_idx, start_idx - 1, -1):
                    if i < len(questions):
                        questions.pop(i)
                await repo.update_field(qid, "questions", questions)
                session["field"] = None
                session.pop("pending_delete", None)
                await m.reply(
                    f"🎉 **Deleted successfully!**\n\nRemoved: **{delete_count}** questions\n"
                    f"Remaining: **{len(questions)}** questions\n\nUse /edit {qid} to continue editing."
                )
            else:
                session["field"] = None
                session.pop("pending_delete", None)
                await m.reply("✅ Deletion cancelled.")
        elif field == "add_perm":
            await _add_permission(m, c, uid, qid, text)
        elif field == "rem_perm":
            await _remove_permission(m, uid, qid, text)
        elif field == "promo_message":
            value = None if text.lower() in ("skip", "no", "none", "/skip") else text
            await QuizRepository(get_db()).update_field(qid, "promo_message", value or "")
            await m.reply(f"📢 Promo {'removed' if value is None else 'updated'}.")
            session["field"] = None
    except Exception as exc:
        logger.exception("handle_edit_text_input failed for field=%s", field)
        await m.reply(f"⚠️ Error: {exc}")


def register(app: Client) -> None:
    app.on_message(filters.command("edit") & filters.private)(edit_cmd)
    app.on_message(filters.command("stopedit") & filters.private)(stopedit_cmd)
    app.on_callback_query(
        filters.regex(r"^(?!stg_|dtc_|plan_|pay_|buy_|qd_|srch_|bat_|prev:|next:|refresh:)")
    )(edit_tree_cb)
    app.on_message(filters.text & filters.private & in_edit_session_filter())(handle_edit_text_input)
