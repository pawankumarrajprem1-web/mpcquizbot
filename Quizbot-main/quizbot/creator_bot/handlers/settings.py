"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from quizbot.database import CreatorSettingsRepository, UserRepository, get_db
from quizbot.shared.utils import is_premium_user

from .. import state
from ..ratelimit import ratelimit

logger = logging.getLogger(__name__)

_DTF_LABELS = {"question": "Question", "explanation": "Explanation", "both": "Both"}


@ratelimit("default")
async def settings_cmd(c: Client, m: Message) -> None:
    """/settings -- view and change creator-level preferences (search
    indexing, default appended text, quick-save quiz defaults)."""
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("🔑 Premium required: /pay")
        return
    await _show_settings(uid, m, edit=False)


async def _show_settings(uid: int, target, edit: bool = True) -> None:
    settings_repo = CreatorSettingsRepository(get_db())
    s = await settings_repo.get(uid)
    indexed = s.get("search_indexed", 1)
    default_text = s.get("default_text") or ""
    dtf = s.get("default_text_field", "both")
    qd = s.get("quiz_defaults") or {}

    idx_label = "ON" if indexed else "OFF"
    dt_preview = (default_text[:40] + "...") if len(default_text) > 40 else (default_text or "Not set")
    dtf_label = _DTF_LABELS.get(dtf, dtf)

    text = (
        "⚙️ **Creator Settings**\n\n"
        f"Search index: **{idx_label}** -- your quizzes {'appear' if indexed else 'do NOT appear'} in /search\n\n"
        f"Default text: `{dt_preview}`\n"
        f"  Appended to: **{dtf_label}**\n\n"
        "**Quick Save defaults** (used after /done):\n"
        f"  Type: `{qd.get('type') or 'Not set'}`\n"
        f"  Promo: `{qd.get('promo') or 'Not set'}`\n"
        f"  Sections: `{qd.get('section') or 'Not set'}`"
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"🔍 Search Index: {idx_label}", callback_data=f"stg_idx_{uid}")],
            [InlineKeyboardButton("📝 Set Default Text", callback_data=f"stg_dt_{uid}")],
            [InlineKeyboardButton(f"➕ Append to: {dtf_label}", callback_data=f"stg_dtf_{uid}")],
            [InlineKeyboardButton("💾 Quick Save Config", callback_data=f"stg_qd_{uid}")],
            [InlineKeyboardButton("🗑️ Clear Default Text", callback_data=f"stg_clr_{uid}")],
        ]
    )
    if edit:
        try:
            await target.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await target.reply(text, reply_markup=kb)


async def _show_quick_defaults(uid: int, message) -> None:
    settings_repo = CreatorSettingsRepository(get_db())
    s = await settings_repo.get(uid)
    qd = s.get("quiz_defaults") or {}
    promo = qd.get("promo") or ""
    typ = qd.get("type") or "not set"
    section = qd.get("section") or "no"
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"📄 Type: {typ}", callback_data=f"stg_qt_{uid}")],
            [InlineKeyboardButton(f"📢 Promo: {'set' if promo else 'empty'}", callback_data=f"stg_qp_{uid}")],
            [InlineKeyboardButton(f"📊 Sections: {section}", callback_data=f"stg_qs_{uid}")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"stg_back_{uid}")],
        ]
    )
    text = (
        "💾 **Quick Save Config**\n\n"
        "Auto-applied after /done -- no manual typing needed.\n\n"
        f"Type: `{typ}`\nPromo: `{promo[:40] if promo else 'empty'}`\nSections: `{section}`"
    )
    try:
        await message.edit_text(text, reply_markup=kb)
    except Exception:
        await message.reply(text, reply_markup=kb)


async def settings_cb(c: Client, cb: CallbackQuery) -> None:
    """`stg_<action>_<uid>` -- all creator-settings callbacks."""
    uid = cb.from_user.id
    data = cb.data  # e.g. "stg_idx_6693636856"
    rest = data[4:]
    sep = rest.find("_")
    if sep == -1:
        await cb.answer("⚠️ Bad data", show_alert=True)
        return
    action, target_uid_str = rest[:sep], rest[sep + 1:]
    try:
        target_uid = int(target_uid_str)
    except ValueError:
        await cb.answer("⚠️ Bad data", show_alert=True)
        return
    if uid != target_uid:
        await cb.answer("🚫 Not yours", show_alert=True)
        return

    settings_repo = CreatorSettingsRepository(get_db())
    s = await settings_repo.get(uid)

    try:
        if action == "idx":
            new_val = 0 if s.get("search_indexed", 1) else 1
            await settings_repo.update(uid, search_indexed=new_val)
            await cb.answer(f"✅ Search index {'ON' if new_val else 'OFF'}")
            await _show_settings(uid, cb.message)

        elif action == "dt":
            session = state.edit_sessions.setdefault(uid, {})
            session["stg_field"] = "default_text"
            await cb.answer("📝 Send your default text now")
            await cb.message.reply("📝 Send the text to auto-append to questions/explanations.\n\nSend `none` to clear.")

        elif action == "dtf":
            opts = ["question", "explanation", "both"]
            cur = s.get("default_text_field", "both")
            nxt = opts[(opts.index(cur) + 1) % 3] if cur in opts else "both"
            await settings_repo.update(uid, default_text_field=nxt)
            await cb.answer(f"✅ Appending to: {_DTF_LABELS[nxt]}")
            await _show_settings(uid, cb.message)

        elif action == "clr":
            await settings_repo.update(uid, default_text=None)
            await cb.answer("🗑️ Default text cleared")
            await _show_settings(uid, cb.message)

        elif action == "back":
            await cb.answer()
            await _show_settings(uid, cb.message)

        elif action == "qd":
            await cb.answer()
            await _show_quick_defaults(uid, cb.message)

        elif action == "qt":
            qd = s.get("quiz_defaults") or {}
            qd["type"] = "paid" if qd.get("type") != "paid" else "free"
            await settings_repo.update(uid, quiz_defaults=qd)
            await cb.answer(f"✅ Type: {qd['type']}")
            await _show_quick_defaults(uid, cb.message)

        elif action == "qp":
            session = state.edit_sessions.setdefault(uid, {})
            session["stg_field"] = "qd_promo"
            await cb.answer("📢 Send promo text now")
            await cb.message.reply("📢 Send promo message (or `none` to clear):")

        elif action == "qs":
            qd = s.get("quiz_defaults") or {}
            qd["section"] = "yes" if qd.get("section", "no") != "yes" else "no"
            await settings_repo.update(uid, quiz_defaults=qd)
            await cb.answer(f"✅ Sections: {qd['section']}")
            await _show_quick_defaults(uid, cb.message)

        else:
            await cb.answer()
    except Exception as exc:
        logger.exception("settings_cb failed")
        try:
            await cb.answer(f"⚠️ Error: {str(exc)[:50]}", show_alert=True)
        except Exception:
            pass


@ratelimit("default")
async def remove_words_cmd(c: Client, m: Message) -> None:
    """/remove word1 word2 ... -- add words to this creator's auto-strip
    filter list (applied to all imported/pasted quiz text)."""
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("🔑 Premium required: /pay")
        return
    if len(m.command) < 2:
        await m.reply(
            "📝 **Word Filter**\n\n"
            "Add words to remove from all quiz text:\n"
            "`/remove word1 word2 ...`\n\n"
            "View your list: /mywords\nClear all: /clearlist"
        )
        return
    words = [w.strip().lower() for w in m.text.split(maxsplit=1)[1].strip().split() if w.strip()]
    user_repo = UserRepository(get_db())
    user = await user_repo.get_or_create(uid)
    current = user.get("remove_words", [])
    added = [w for w in words if w not in current]
    current.extend(added)
    await user_repo.update_remove_words(uid, current)
    if added:
        await m.reply(f"✅ Added to filter list: `{', '.join(added)}`\n\nTotal words: **{len(current)}**")
    else:
        await m.reply(f"ℹ️ All words already in your list. Total: **{len(current)}** words. /mywords")


@ratelimit("default")
async def mywords_cmd(c: Client, m: Message) -> None:
    """/mywords -- show this creator's current word filter list."""
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("🔑 Premium required: /pay")
        return
    user = await UserRepository(get_db()).get_or_create(uid)
    words = user.get("remove_words", [])
    if not words:
        await m.reply("📝 Your filter list is empty.\nAdd words: `/remove word1 word2`")
        return
    lines = "\n".join(f"{i + 1}. `{w}`" for i, w in enumerate(words))
    await m.reply(
        f"📝 **Your Word Filter List** ({len(words)} words)\n\n{lines}\n\n"
        f"These are auto-removed from quiz text.\nClear all: /clearlist"
    )


@ratelimit("default")
async def clearlist_cmd(c: Client, m: Message) -> None:
    """/clearlist -- clear this creator's word filter list."""
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("🔑 Premium required: /pay")
        return
    await UserRepository(get_db()).update_remove_words(uid, [])
    await m.reply("✅ Filter list cleared.")


def register(app: Client) -> None:
    app.on_message(filters.command("settings") & filters.private)(settings_cmd)
    app.on_callback_query(filters.regex(r"^stg_"))(settings_cb)
    app.on_message(filters.command("remove") & filters.private)(remove_words_cmd)
    app.on_message(filters.command("mywords") & filters.private)(mywords_cmd)
    app.on_message(filters.command("clearlist") & filters.private)(clearlist_cmd)
