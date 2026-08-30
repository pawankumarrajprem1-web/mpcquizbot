"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def quiz_editor_main_kb(qid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⚙️ Settings", callback_data=f"set_{qid}"),
                InlineKeyboardButton("❓ Questions", callback_data=f"qmgr_{qid}"),
            ],
            [
                InlineKeyboardButton("🔀 Shuffle", callback_data=f"shuf_{qid}"),
                InlineKeyboardButton("🔐 Permissions", callback_data=f"perms_{qid}"),
            ],
            [
                InlineKeyboardButton("📤 Export", callback_data=f"exp_{qid}"),
                InlineKeyboardButton("✖️ Close", callback_data=f"close_{qid}"),
            ],
        ]
    )


def quiz_editor_settings_kb(qid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🏷️ Name", callback_data=f"ename_{qid}"),
                InlineKeyboardButton("⏱️ Timer", callback_data=f"etimer_{qid}"),
            ],
            [
                InlineKeyboardButton("🏷️ Type", callback_data=f"etype_{qid}"),
                InlineKeyboardButton("➖ Negative marking", callback_data=f"eneg_{qid}"),
            ],
            [InlineKeyboardButton("📢 Promo", callback_data=f"epromo_{qid}")],
            [InlineKeyboardButton("◀️ Back", callback_data=f"main_{qid}")],
        ]
    )


def quiz_editor_qmgr_kb(qid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👁️ View / Edit", callback_data=f"view_{qid}_0"),
                InlineKeyboardButton("➕ Add", callback_data=f"add_{qid}"),
            ],
            [InlineKeyboardButton("🗑️ Delete range", callback_data=f"delrange_{qid}")],
            [InlineKeyboardButton("◀️ Back", callback_data=f"main_{qid}")],
        ]
    )


def batch_kb(bid: str, uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👥 Add Chat", callback_data=f"bat_addchat_{bid}_{uid}"),
                InlineKeyboardButton("🚫 Remove Chat", callback_data=f"bat_rmchat_{bid}_{uid}"),
            ],
            [
                InlineKeyboardButton("➕ Add Quiz", callback_data=f"bat_addqz_{bid}_{uid}"),
                InlineKeyboardButton("➖ Remove Quiz", callback_data=f"bat_rmqz_{bid}_{uid}"),
            ],
            [
                InlineKeyboardButton("✍️ Edit", callback_data=f"bat_edit_{bid}_{uid}"),
                InlineKeyboardButton("🗑️ Delete", callback_data=f"bat_del_{bid}_{uid}"),
            ],
            [InlineKeyboardButton("📦 My Batches", callback_data=f"bat_list_{uid}")],
        ]
    )
