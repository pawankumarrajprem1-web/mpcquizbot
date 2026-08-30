"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

from pyrogram import Client

from . import (
    admin,
    ai_keys,
    auth,
    batches,
    file_import,  # noqa: F401 -- imported for side-effect-free reuse by quiz_creation
    inline,
    payments,
    quiz_creation,
    quiz_editing,
    quiz_management,
    reports,
    settings,
)

__all__ = ["register"]


def register(app: Client) -> None:
    """Register every handler module's commands/callbacks on `app`."""
    admin.register(app)
    auth.register(app)
    payments.register(app)
    ai_keys.register(app)
    settings.register(app)
    quiz_management.register(app)
    batches.register(app)
    reports.register(app)
    quiz_editing.register(app)
    quiz_creation.register(app)
    inline.register(app)
