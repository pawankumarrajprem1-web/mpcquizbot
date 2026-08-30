"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging
import time
import uuid

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from quizbot.shared import config

from .. import state
from ..payments_util import calc_price, create_payment_link
from ..ratelimit import ratelimit

logger = logging.getLogger(__name__)

PAYMENT_SESSION_SECONDS = 900  # 15 minutes

# quantity choices offered per plan
_QTY_CHOICES: dict[str, list[int]] = {
    "1_month": [1, 2, 3, 6, 12],
    "3_month": [1, 2, 4],
    "1_year": [1, 2, 3],
}


def _plans_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(plan["label"], callback_data=f"plan_{key}")
                for key, plan in config.PLANS.items()
            ]
        ]
    )


def _plans_overview_text() -> str:
    lines = ["Choose a plan for **Premium Access**:\n"]
    for plan in config.PLANS.values():
        rupees = plan["amount"] / 100
        lines.append(f"**{plan['label']}** -- Rs.{rupees:.0f} / {plan['days']} days")
    return "\n".join(lines)


@ratelimit("default")
async def pay_cmd(c: Client, m: Message) -> None:
    """/pay -- show the available premium plans."""
    await m.reply(
        f"Hello **{m.from_user.first_name}**!\n\n{_plans_overview_text()}",
        reply_markup=_plans_kb(),
    )


async def plan_select_cb(c: Client, cq: CallbackQuery) -> None:
    """`plan_<key>` -- show quantity/duration choices for one plan."""
    plan_key = cq.data.split("_", 1)[1]
    if plan_key not in config.PLANS:
        await cq.answer("Unknown plan", show_alert=True)
        return
    plan = config.PLANS[plan_key]
    rows = []
    for qty in _QTY_CHOICES.get(plan_key, [1]):
        info = calc_price(plan_key, qty)
        disc = f" (-{info['discount_pct']}%)" if info["discount_pct"] else ""
        label = f"{info['days']} days -- Rs.{info['price']}{disc}"
        rows.append([InlineKeyboardButton(label, callback_data=f"buy_{plan_key}_{qty}")])
    rows.append([InlineKeyboardButton("Back", callback_data="pay_back")])
    await cq.message.edit_text(
        f"**{plan['label']} Plan** -- select duration:", reply_markup=InlineKeyboardMarkup(rows)
    )
    await cq.answer()


async def pay_back_cb(c: Client, cq: CallbackQuery) -> None:
    """`pay_back` -- return to the top-level plan chooser."""
    await cq.message.edit_text(_plans_overview_text(), reply_markup=_plans_kb())
    await cq.answer()


async def buy_plan_cb(c: Client, cq: CallbackQuery) -> None:
    """`buy_<plan_key>_<qty>` -- create a Razorpay payment link and store
    the pending payment, to be resolved when the user returns via
    `/start?start=pay_<token>`."""
    _, plan_key, qty_str = cq.data.split("_", 2)
    if plan_key not in config.PLANS:
        await cq.answer("Unknown plan", show_alert=True)
        return
    qty = int(qty_str)
    uid = cq.from_user.id
    info = calc_price(plan_key, qty)
    await cq.message.edit_text("Creating payment link...")

    token = uuid.uuid4().hex[:24]
    bot_username = (await c.get_me()).username
    link = await create_payment_link(info["price"], token, bot_username)
    if not link or not link.get("short_url"):
        await cq.message.edit_text("Could not create payment link. Try again later.")
        return

    state.pending_payments[token] = {
        "uid": uid,
        "days": info["days"],
        "plan_label": f"{info['label']} x{qty}",
        "price": info["price"],
        "link_id": link.get("id", ""),
        "expires_at": int(time.time()) + PAYMENT_SESSION_SECONDS,
    }

    disc_line = (
        f"\nDiscount: **{info['discount_pct']}% off** (Rs.{info['original']} -> Rs.{info['price']})"
        if info["discount_pct"]
        else ""
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"Pay Rs.{info['price']}", url=link["short_url"])],
            [InlineKeyboardButton("Back", callback_data=f"plan_{plan_key}")],
        ]
    )
    await cq.message.edit_text(
        f"**Payment Details**\n\n"
        f"Plan: **{info['label']} x{qty}**\n"
        f"Duration: **{info['days']} days**\n"
        f"Amount: **Rs.{info['price']}**{disc_line}\n\n"
        f"Tap **Pay** -- after payment you'll be redirected back here and premium "
        f"activated instantly.",
        reply_markup=kb,
    )
    await cq.answer()


def register(app: Client) -> None:
    app.on_message(filters.command("pay") & filters.private)(pay_cmd)
    app.on_callback_query(filters.regex(r"^plan_"))(plan_select_cb)
    app.on_callback_query(filters.regex(r"^pay_back$"))(pay_back_cb)
    app.on_callback_query(filters.regex(r"^buy_"))(buy_plan_cb)
