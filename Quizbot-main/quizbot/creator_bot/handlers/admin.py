"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import asyncio
import logging
import time

from pyrogram import Client, filters
from pyrogram.types import Message

from quizbot.database import (
    LeaderboardRepository,
    QuizRepository,
    UserRepository,
    get_db,
)
from quizbot.shared import config
from quizbot.shared.rich_quiz import send_rich_or_fallback
from quizbot.shared.utils.http import request_json

from .. import state
from ..premium_grant import grant_and_notify
from ..ratelimit import ratelimit

logger = logging.getLogger(__name__)

FEATURES_TEXT = (
    "**Features**\n\n"
    "- Create questions from text, with the correct option marked\n"
    "- Marathon quiz mode\n"
    "- Convert forwarded polls into quiz questions\n"
    "- Smart word filtering\n"
    "- Bulk question import (paste or .txt file)\n"
    "- Negative marking\n"
    "- Full quiz editor (rename, timer, type, questions, permissions)\n"
    "- Quiz analytics and leaderboards\n"
    "- Inline query support for sharing quizzes\n"
    "- Free and paid quizzes with batch bundling\n"
    "- HTML exam-style and analysis reports\n"
    "- Sectional quizzes with per-section timers\n"
)

HELP_TEXT = (
    "**Creator Bot -- Command Guide**\n\n"
    "**Creating & managing quizzes**\n"
    "`/create` -- start creating a new quiz\n"
    "`/done` -- finish and save the quiz you're creating\n"
    "`/cancel` -- cancel the quiz you're currently creating\n"
    "`/edit <id>` -- edit one of your existing quizzes\n"
    "`/del <id>` -- delete one of your quizzes\n"
    "`/remall` -- clear your paid-quiz chat authorizations\n"
    "`/info <id>` -- show details about a quiz\n\n"
    "**Finding & sharing**\n"
    "`/myquizzes [term]` -- list (or search) your quizzes\n"
    "`/search word` (or `/quiz`) -- search all public quizzes\n"
    "`/leaders <id>` (or `/aspirants`) -- full leaderboard\n\n"
    "**Paid quiz access**\n"
    "`/add <chat_id>` -- authorize a chat for your paid quizzes\n"
    "`/rem <chat_id>` -- remove a chat's access\n"
    "`/setpromo text` -- set a promo message on all your quizzes\n\n"
    "**Reports**\n"
    "`/whtml <id>` -- interactive HTML quiz report\n"
    "`/testseries <ids>` -- PDF test-series generator (if configured)\n\n"
    "**AI keys**\n"
    "`/setkey provider key`, `/mykeys`, `/delkey provider`\n\n"
    "**Word filters**\n"
    "`/remove word1 word2`, `/mywords`, `/clearlist`\n\n"
    "**Batches**\n"
    "`/batch`, `/createbatch`, `/searchbatch term`\n\n"
    "**Account**\n"
    "`/pay` -- buy or renew premium\n"
    "`/settings` -- creator settings\n"
    "`/features` -- feature overview\n"
)


@ratelimit("default")
async def start_cmd(c: Client, m: Message) -> None:
    """/start -- silent unless it's a Razorpay payment deep-link
    (`?start=pay_<token>`).

    Both bots share one Telegram token in this deployment, and the Runner
    Bot owns the user-facing /start welcome message -- so this handler must
    stay registered (Telegram always delivers a deep-link payload as
    `/start`, there's no way to route it to another command name) but does
    nothing visible for a bare /start with no payload, to avoid a second,
    conflicting welcome message. See `runner_bot/handlers/admin.py` for the
    shared /start and /help text.
    """
    uid = m.from_user.id
    await UserRepository(get_db()).get_or_create(uid)

    args = m.text.split(maxsplit=1)
    param = args[1].strip() if len(args) > 1 else ""

    if param.startswith("pay_"):
        token = param[4:]
        entry = state.pending_payments.get(token)
        if not entry:
            await m.reply(
                "Payment session expired or not found.\n"
                "If you completed payment, contact support with /help."
            )
            return
        if entry["uid"] != uid:
            await m.reply("This payment link belongs to a different account.")
            return
        if time.time() > entry["expires_at"]:
            state.pending_payments.pop(token, None)
            await m.reply("Session expired (15 min limit). Use /pay to start again.")
            return

        state.pending_payments.pop(token, None)
        days = entry["days"]
        try:
            fmt = await grant_and_notify(uid, days)
        except Exception:
            # Grant failed (e.g. a transient DB error) -- re-queue the
            # pending payment so a retry of the /start deep-link can pick
            # it back up, and tell the user honestly instead of claiming
            # success. Matches the original bot's failure-path behavior.
            logger.error("grant_and_notify failed for uid=%s token=%s", uid, token, exc_info=True)
            state.pending_payments[token] = entry
            await m.reply(
                "⚠️ Payment received but activation failed.\n"
                f"Contact support with this token: `{token}`"
            )
            return

        try:
            if config.OWNER_ID:
                await c.send_message(
                    config.OWNER_ID,
                    f"Payment received!\nUser: `{uid}` | Plan: {entry['plan_label']} | "
                    f"{days}d | Rs.{entry['price']} | Link: `{entry['link_id']}`",
                )
        except Exception:
            logger.debug("Failed to notify owner of payment", exc_info=True)

        await m.reply(
            f"**Premium activated!**\n\n"
            f"Plan: **{entry['plan_label']}**\n"
            f"Valid until: `{fmt} IST`\n\n"
            f"Enjoy your premium features."
        )
        return

    # Bare /start, no payment payload -- intentionally silent. The Runner
    # Bot's /start owns the welcome message for this deployment.
    return


@ratelimit("default")
async def help_cmd(c: Client, m: Message) -> None:
    """/help -- full command reference."""
    await m.reply(HELP_TEXT, disable_web_page_preview=True)


@ratelimit("default")
async def features_cmd(c: Client, m: Message) -> None:
    """/features -- short marketing-style feature overview."""
    await m.reply(FEATURES_TEXT, disable_web_page_preview=True)


async def limit_cmd(c: Client, m: Message) -> None:
    """/limit -- show the caller's current rate-limit usage."""
    await m.reply(state.rate_limit_status_text(m.from_user.id))


def _is_owner_or_admin(user_id: int) -> bool:
    return user_id == config.OWNER_ID or user_id in config.ADMIN_IDS


async def gcast_cmd(c: Client, m: Message) -> None:
    """/gcast -- (owner/admin only) broadcast the replied-to message to
    every registered user."""
    uid = m.from_user.id
    if not _is_owner_or_admin(uid):
        return
    if not m.reply_to_message:
        await m.reply("Reply to the message you want to broadcast.")
        return
    if state.broadcast.active:
        await m.reply("A broadcast is already active. Use /stopcast to stop it.")
        return

    state.broadcast.active = True
    bm = m.reply_to_message
    users = await UserRepository(get_db()).get_all(limit=1_000_000)
    total, sent, failed = len(users), 0, 0
    progress = await m.reply(f"Starting broadcast: 0/{total}")

    for i, u in enumerate(users):
        if not state.broadcast.active:
            await progress.edit_text(f"Stopped at {sent}/{total}")
            return
        cid = u["chat_id"]
        try:
            if bm.text:
                await c.send_message(cid, bm.text, reply_markup=bm.reply_markup)
            elif bm.photo:
                await c.send_photo(cid, bm.photo.file_id, caption=bm.caption or "", reply_markup=bm.reply_markup)
            elif bm.video:
                await c.send_video(cid, bm.video.file_id, caption=bm.caption or "", reply_markup=bm.reply_markup)
            elif bm.document:
                await c.send_document(cid, bm.document.file_id, caption=bm.caption or "", reply_markup=bm.reply_markup)
            else:
                await bm.copy(cid)
            sent += 1
        except Exception:
            failed += 1
        if (i + 1) % 100 == 0:
            await progress.edit_text(f"Progress: {sent}/{total}")
            await asyncio.sleep(10)

    state.broadcast.active = False
    await progress.edit_text(f"Done: {sent}/{total} sent, {failed} failed")


async def stopcast_cmd(c: Client, m: Message) -> None:
    """/stopcast -- (owner/admin only) interrupt an active /gcast run."""
    if not _is_owner_or_admin(m.from_user.id):
        return
    if not state.broadcast.active:
        await m.reply("No active broadcast.")
        return
    state.broadcast.active = False
    await m.reply("Broadcast stopped.")


@ratelimit("default")
async def statses_cmd(c: Client, m: Message) -> None:
    """/statses -- overall platform stats (users, quizzes, paid/free)."""
    status = await m.reply("Fetching...")
    try:
        user_stats = await UserRepository(get_db()).stats()
        quiz_stats = await QuizRepository(get_db()).stats()
        await status.edit_text(
            "**Platform Stats**\n\n"
            f"Users: `{user_stats['total_users']}` (premium: `{user_stats['premium_users']}`)\n"
            f"Quizzes: `{quiz_stats['total_quizzes']}`\n"
            f"Paid: `{quiz_stats['paid_quizzes']}`\n"
            f"Free: `{quiz_stats['free_quizzes']}`"
        )
    except Exception as exc:
        logger.exception("statses_cmd failed")
        await status.edit_text(f"Error: {exc}")


async def testapi_cmd(c: Client, m: Message) -> None:
    """/testapi -- (owner only) sanity-check DB connectivity. Replaces the
    legacy PHP-API connectivity test now that everything is MongoDB."""
    if m.from_user.id != config.OWNER_ID:
        return
    status = await m.reply("🔄 Testing database connectivity...")
    try:
        db = get_db()
        await db.db.command("ping")
        user_stats = await UserRepository(db).stats()
        quiz_stats = await QuizRepository(db).stats()
        await status.edit_text(
            "✅ **DB connectivity: OK**\n\n"
            f"Users: `{user_stats['total_users']}`\n"
            f"Quizzes: `{quiz_stats['total_quizzes']}`\n"
            f"DB: `MongoDB / {config.MONGODB_DB_NAME}`"
        )
    except Exception as exc:
        logger.exception("testapi_cmd failed")
        await status.edit_text(f"❌ DB connectivity FAILED: {exc}")


LEADERS_PAGE_SIZE = config.LEADERS_PAGE_SIZE


def _leaders_rich_md(quiz_name: str, rows: list[dict], start_rank: int) -> str:
    """Build a GFM markdown table for sendRichMessage (up to ~32k chars per
    message vs. the normal 4096 limit -- lets a full 200-row leaderboard
    page go out as one nicely formatted message instead of many)."""
    lines = [
        f"### \U0001F3C5 Leading Aspirants -- {quiz_name}",
        "",
        "| # | Name | Score | Qs | Time |",
        "|--:|:-----|------:|---:|-----:|",
    ]
    for j, r in enumerate(rows, start=start_rank):
        icon = "\U0001F947" if j == 1 else "\U0001F948" if j == 2 else "\U0001F949" if j == 3 else str(j)
        name = str(r.get("user_name") or "Player")[:22].replace("|", "\\|")
        secs = r.get("time_taken", 0) or 0
        mn, sc = divmod(int(secs), 60)
        lines.append(f"| {icon} | {name} | {r.get('score', 0)} | {r.get('total_questions', 0)} | {mn}m {sc}s |")
    return "\n".join(lines)


async def _send_raw_bot_api(method: str, params: dict) -> dict:
    """Adapter for `quizbot.shared.rich_quiz`: Pyrogram has no HTTP Bot API
    client (it speaks MTProto directly), so sendRichMessage -- a Bot-API-only
    method (Bot API 10.1) -- is called over plain HTTPS instead, exactly as
    the original bot did."""
    url = f"https://api.telegram.org/bot{config.CREATOR_BOT_TOKEN}/{method}"
    status, body = await request_json("POST", url, json_body=params, retries=1)
    if status != 200 or not isinstance(body, dict) or not body.get("ok"):
        raise RuntimeError(f"{method} failed: HTTP {status} {body}")
    return body


@ratelimit("default")
async def leaders_cmd(c: Client, m: Message) -> None:
    """/leaders <quiz_id> (or /aspirants) -- full ranked leaderboard for a
    quiz. Each page is sent as a single sendRichMessage GFM table when
    possible (up to ~32k chars), falling back automatically to chunked
    plain-text messages if the receiving client/Bot API doesn't support it."""
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        await m.reply("Usage: `/leaders QUIZID`")
        return
    qid = parts[1].strip()

    quiz = await QuizRepository(get_db()).get(qid)
    if not quiz:
        await m.reply("Quiz not found.")
        return

    board = LeaderboardRepository(get_db())
    rows = await board.page(qid, offset=0, limit=LEADERS_PAGE_SIZE)
    if not rows:
        await m.reply("No one has attempted this quiz yet.")
        return

    status = await m.reply(f"Found {len(rows)}+ aspirant(s). Sending leaderboard...")
    offset, rank = 0, 1
    page_rows = rows
    while page_rows:
        rich_md = _leaders_rich_md(quiz["quiz_name"], page_rows, rank)
        await send_rich_or_fallback(
            _send_raw_bot_api,
            lambda text: m.reply(text),
            m.chat.id,
            rich_md,
            plain_limit=3500,
        )
        rank += len(page_rows)
        offset += LEADERS_PAGE_SIZE
        page_rows = await board.page(qid, offset=offset, limit=LEADERS_PAGE_SIZE)
        if page_rows:
            await asyncio.sleep(1)

    try:
        await status.delete()
    except Exception:
        pass


def register(app: Client) -> None:
    app.on_message(filters.command("start") & filters.private)(start_cmd)
    app.on_message(filters.command("help"))(help_cmd)
    app.on_message(filters.command("features"))(features_cmd)
    app.on_message(filters.command("limit") & filters.private)(limit_cmd)
    app.on_message(filters.command("gcast") & filters.private)(gcast_cmd)
    app.on_message(filters.command("stopcast") & filters.private)(stopcast_cmd)
    app.on_message(filters.command("statses") & filters.private)(statses_cmd)
    app.on_message(filters.command("testapi") & filters.private)(testapi_cmd)
    app.on_message(filters.command(["leaders", "aspirants"]) & filters.private)(leaders_cmd)
