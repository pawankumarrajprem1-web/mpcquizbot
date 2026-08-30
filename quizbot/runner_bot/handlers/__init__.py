"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

from telegram.ext import Application

from . import admin, ai_quiz, mix, pdf_quiz, poll_quiz, quiz_play, reports, scheduling, setup_wizard, translation

_MODULES = (
    quiz_play,     # /start, /pause, /resume, /stop, /leaderboard, /slow, /fast, /normal, poll answers
    setup_wizard,  # qs_* quiz-setup wizard callbacks
    poll_quiz,     # /pollquiz, /pollstop
    mix,           # /mix
    ai_quiz,       # /aiquiz
    pdf_quiz,      # /pdfquiz
    reports,       # /html, /pdf, compare_ callback
    scheduling,    # /schedule, /viewschedule, /cancelschedule
    translation,   # /trans
    admin,         # /help, channel command routing (registered last so it doesn't
                   # shadow the more specific per-feature MessageHandlers above)
)


def register(application: Application) -> None:
    """Register every handler module's commands/callbacks on `application`."""
    for module in _MODULES:
        module.register(application)
