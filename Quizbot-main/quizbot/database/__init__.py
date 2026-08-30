"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from .db import Database, get_db, init_db, close_db
from .repositories import (
    UserRepository,
    QuizRepository,
    AuthChatRepository,
    PaymentRepository,
    AIKeyRepository,
    AttemptRepository,
    LeaderboardRepository,
    QuestionStatsRepository,
    MistakeRepository,
    CreatorSettingsRepository,
    ChatSettingsRepository,
    QuizPrefsRepository,
    BatchRepository,
)

__all__ = [
    "Database",
    "get_db",
    "init_db",
    "close_db",
    "UserRepository",
    "QuizRepository",
    "AuthChatRepository",
    "PaymentRepository",
    "AIKeyRepository",
    "AttemptRepository",
    "LeaderboardRepository",
    "QuestionStatsRepository",
    "MistakeRepository",
    "CreatorSettingsRepository",
    "ChatSettingsRepository",
    "QuizPrefsRepository",
    "BatchRepository",
]
