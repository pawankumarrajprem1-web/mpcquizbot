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

from quizbot.database import BatchRepository, get_db
from quizbot.shared.utils import is_premium_user

from .. import state
from ..keyboards import batch_kb
from ..ratelimit import ratelimit

logger = logging.getLogger(__name__)


async def _show_batch(uid: int, bid: str, target) -> None:
    repo = BatchRepository(get_db())
    b = await repo.get(bid)
    if not b:
        text = "❌ Batch not found."
        try:
            await target.edit_text(text)
        except Exception:
            await target.reply(text)
        return
    chats = ", ".join(str(x) for x in b.get("chats") or []) or "None"
    quizzes = ", ".join(b.get("quizzes") or []) or "None"
    text = (
        f"📦 **{b['name']}**  `{bid}`\n\n"
        f"{b.get('description') or 'No description'}\n"
        f"Contact: {b.get('contact_info') or 'Not set'}\n"
        f"💳 Payment: {b.get('payment_link') or 'Not set'}\n\n"
        f"👥 Auth chats: `{chats}`\n"
        f"📋 Quizzes: `{quizzes}`"
    )
    kb = batch_kb(bid, uid)
    try:
        await target.edit_text(text, reply_markup=kb)
    except Exception:
        await target.reply(text, reply_markup=kb)


async def _show_batch_list(uid: int, target) -> None:
    repo = BatchRepository(get_db())
    batches = await repo.list_by_creator(uid)
    kb_new = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Create Batch", callback_data=f"bat_new_{uid}")]])
    if not batches:
        text = "📦 No batches yet."
        try:
            await target.edit_text(text, reply_markup=kb_new)
        except Exception:
            await target.reply(text, reply_markup=kb_new)
        return
    buttons = [
        [
            InlineKeyboardButton(
                f"{b['name'][:30]} ({len(b.get('quizzes') or [])} quizzes)",
                callback_data=f"bat_view_{b['batch_id']}_{uid}",
            )
        ]
        for b in batches[:10]
    ]
    buttons.append([InlineKeyboardButton("➕ New Batch", callback_data=f"bat_new_{uid}")])
    text = f"📦 **Your Batches** ({len(batches)})"
    kb = InlineKeyboardMarkup(buttons)
    try:
        await target.edit_text(text, reply_markup=kb)
    except Exception:
        await target.reply(text, reply_markup=kb)


@ratelimit("default")
async def batch_cmd(c: Client, m: Message) -> None:
    """/batch -- list this creator's batches."""
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("🔒 Premium only: /pay")
        return
    await _show_batch_list(uid, m)


@ratelimit("default")
async def createbatch_cmd(c: Client, m: Message) -> None:
    """/createbatch -- start the batch-creation wizard (name -> description
    -> contact -> payment link)."""
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("🔒 Premium only: /pay")
        return
    state.batch_sessions[uid] = {"step": "name"}
    await m.reply("📦 **Create Batch**\n\nSend batch name:")


@ratelimit("default")
async def searchbatch_cmd(c: Client, m: Message) -> None:
    """/searchbatch <term> -- search public batches by name."""
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        await m.reply("⚠️ Usage: /searchbatch <term>")
        return
    results = await BatchRepository(get_db()).search(args[1].strip())
    if not results:
        await m.reply("🔍 No batches found.")
        return
    lines = []
    for b in results:
        lines.append(
            f"📦 **{b['name']}** `{b['batch_id']}`\n"
            f"   {(b.get('description') or '')[:60]}"
        )
    await m.reply("\n\n".join(lines)[:4000])


async def batch_cb(c: Client, cb: CallbackQuery) -> None:
    """`bat_<action>_...` -- the full batch-management callback tree."""
    uid = cb.from_user.id
    parts = cb.data.split("_")
    action = parts[1]
    repo = BatchRepository(get_db())

    if action == "list":
        if uid != int(parts[2]):
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        await cb.answer()
        await _show_batch_list(uid, cb.message)
        return

    if action == "new":
        if uid != int(parts[2]):
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        state.batch_sessions[uid] = {"step": "name"}
        await cb.answer()
        await cb.message.reply("📦 Send batch name:")
        return

    if action == "view":
        bid, target_uid = parts[2], int(parts[3])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        await cb.answer()
        await _show_batch(uid, bid, cb.message)
        return

    if action == "attachqz":
        qid, target_uid = parts[2], int(parts[3])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        batches = await repo.list_by_creator(uid)
        if not batches:
            state.batch_sessions[uid] = {"step": "name", "_pending_qid": qid}
            await cb.answer()
            await cb.message.reply("📦 No batches yet. Send a name to create one and auto-attach:")
            return
        buttons = [
            [InlineKeyboardButton(b["name"][:35], callback_data=f"bat_doattach_{b['batch_id']}_{qid}_{uid}")]
            for b in batches[:8]
        ]
        buttons.append([InlineKeyboardButton("➕ New Batch", callback_data=f"bat_newforqz_{qid}_{uid}")])
        await cb.answer()
        await cb.message.reply("📦 Select batch:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if action == "doattach":
        bid, qid, target_uid = parts[2], parts[3], int(parts[4])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        await repo.add_quiz(bid, qid)
        await cb.answer("✅ Quiz attached!")
        await _show_batch(uid, bid, cb.message)
        return

    if action == "newforqz":
        qid, target_uid = parts[2], int(parts[3])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        state.batch_sessions[uid] = {"step": "name", "_pending_qid": qid}
        await cb.answer()
        await cb.message.reply("📦 Send batch name:")
        return

    if action == "addchat":
        bid, target_uid = parts[2], int(parts[3])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        state.batch_sessions[uid] = {"step": "addchat", "bid": bid}
        await cb.answer()
        await cb.message.reply("👥 Send group/channel ID (e.g. -100123456):")
        return

    if action == "rmchat":
        bid, target_uid = parts[2], int(parts[3])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        b = await repo.get(bid)
        chats = b.get("chats", []) if b else []
        if not chats:
            await cb.answer("⚠️ No chats authorized", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(str(cid), callback_data=f"bat_dorm_{bid}_{cid}_{uid}")] for cid in chats[:10]]
        await cb.answer()
        await cb.message.reply("➖ Select chat to remove:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if action == "dorm":
        bid, chat_id_s, target_uid = parts[2], parts[3], int(parts[4])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        await repo.remove_chat(bid, int(chat_id_s))
        await cb.answer("✅ Removed!")
        await _show_batch(uid, bid, cb.message)
        return

    if action == "addqz":
        bid, target_uid = parts[2], int(parts[3])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        state.batch_sessions[uid] = {"step": "addqz", "bid": bid}
        await cb.answer()
        await cb.message.reply("🆔 Send quiz ID:")
        return

    if action == "rmqz":
        bid, target_uid = parts[2], int(parts[3])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        b = await repo.get(bid)
        quizzes = b.get("quizzes", []) if b else []
        if not quizzes:
            await cb.answer("⚠️ No quizzes", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(qid, callback_data=f"bat_dormqz_{bid}_{qid}_{uid}")] for qid in quizzes[:10]]
        await cb.answer()
        await cb.message.reply("➖ Select quiz to remove:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if action == "dormqz":
        bid, qid, target_uid = parts[2], parts[3], int(parts[4])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        await repo.remove_quiz(bid, qid)
        await cb.answer("✅ Removed!")
        await _show_batch(uid, bid, cb.message)
        return

    if action == "edit":
        bid, target_uid = parts[2], int(parts[3])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Name", callback_data=f"bat_ef_name_{bid}_{uid}"),
                    InlineKeyboardButton("Description", callback_data=f"bat_ef_desc_{bid}_{uid}"),
                ],
                [
                    InlineKeyboardButton("Contact", callback_data=f"bat_ef_contact_{bid}_{uid}"),
                    InlineKeyboardButton("💳 Payment", callback_data=f"bat_ef_payment_{bid}_{uid}"),
                ],
            ]
        )
        await cb.answer()
        await cb.message.reply("✏️ What to edit?", reply_markup=kb)
        return

    if action == "ef":
        field, bid, target_uid = parts[2], parts[3], int(parts[4])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        prompts = {
            "name": "✏️ Send new name:",
            "desc": "✏️ Send new description:",
            "contact": "✏️ Send contact info:",
            "payment": "💳 Send payment link:",
        }
        state.batch_sessions[uid] = {"step": f"edit_{field}", "bid": bid}
        await cb.answer()
        await cb.message.reply(prompts.get(field, "✏️ Send value:"))
        return

    if action == "del":
        bid, target_uid = parts[2], int(parts[3])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Yes, delete", callback_data=f"bat_delconfirm_{bid}_{uid}"),
                    InlineKeyboardButton("❌ Cancel", callback_data=f"bat_view_{bid}_{uid}"),
                ]
            ]
        )
        await cb.answer()
        await cb.message.reply(f"🗑️ Delete batch `{bid}`?", reply_markup=kb)
        return

    if action == "delconfirm":
        bid, target_uid = parts[2], int(parts[3])
        if uid != target_uid:
            await cb.answer("⚠️ Not yours", show_alert=True)
            return
        await repo.delete(bid)
        await cb.answer("🗑️ Deleted!")
        await _show_batch_list(uid, cb.message)
        return

    await cb.answer()


async def batch_input(c: Client, m: Message) -> None:
    """Free-text steps of the batch-creation/edit wizard. Only fires for
    users currently inside a batch session (see handlers/__init__.py's
    filter registration)."""
    uid = m.from_user.id
    session = state.batch_sessions[uid]
    step = session.get("step", "")
    text = m.text.strip()
    repo = BatchRepository(get_db())

    if step == "name":
        session["name"] = text
        session["step"] = "desc"
        await m.reply("✏️ Description (or 'skip'):")
        return

    if step == "desc":
        session["desc"] = None if text.lower() == "skip" else text
        session["step"] = "contact"
        await m.reply("👥 Contact info -- @username / WhatsApp / email (or 'skip'):")
        return

    if step == "contact":
        session["contact"] = None if text.lower() == "skip" else text
        session["step"] = "payment"
        await m.reply("💳 Payment link (or 'skip'):")
        return

    if step == "payment":
        session["payment"] = None if text.lower() == "skip" else text
        batch = await repo.create(
            uid,
            session["name"],
            description=session.get("desc"),
            contact_info=session.get("contact"),
            payment_link=session.get("payment"),
        )
        bid = batch["batch_id"]
        pending_qid = session.get("_pending_qid")
        if pending_qid:
            await repo.add_quiz(bid, pending_qid)
        state.batch_sessions.pop(uid, None)
        suffix = f"\n✅ Quiz `{pending_qid}` attached!" if pending_qid else ""
        await m.reply(f"✅ Batch **{session['name']}** created! ID: `{bid}`{suffix}")
        await _show_batch(uid, bid, m)
        return

    if step == "addchat":
        try:
            chat_id = int(text)
        except ValueError:
            await m.reply("⚠️ Send a numeric chat ID, e.g. -100123456")
            return
        await repo.add_chat(session["bid"], chat_id)
        bid = session["bid"]
        state.batch_sessions.pop(uid, None)
        await m.reply(f"✅ Chat `{chat_id}` authorized!")
        await _show_batch(uid, bid, m)
        return

    if step == "addqz":
        await repo.add_quiz(session["bid"], text)
        bid = session["bid"]
        state.batch_sessions.pop(uid, None)
        await m.reply(f"✅ Quiz `{text}` added!")
        await _show_batch(uid, bid, m)
        return

    if step.startswith("edit_"):
        field_map = {
            "edit_name": "name",
            "edit_desc": "description",
            "edit_contact": "contact_info",
            "edit_payment": "payment_link",
        }
        field = field_map.get(step)
        bid = session["bid"]
        if field:
            await repo.update(bid, **{field: text})
            state.batch_sessions.pop(uid, None)
            await m.reply("✅ Updated!")
            await _show_batch(uid, bid, m)
        return


def in_batch_session_filter():
    async def func(_, __, m: Message) -> bool:
        return bool(m.from_user) and m.from_user.id in state.batch_sessions

    return filters.create(func)


def register(app: Client) -> None:
    app.on_message(filters.command("batch") & filters.private)(batch_cmd)
    app.on_message(filters.command("createbatch") & filters.private)(createbatch_cmd)
    app.on_message(filters.command("searchbatch") & filters.private)(searchbatch_cmd)
    app.on_callback_query(filters.regex(r"^bat_"))(batch_cb)
    app.on_message(filters.private & filters.text & in_batch_session_filter())(batch_input)
