"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class Database:
    """Thin holder for the shared Motor client/database handle, plus the
    one-time index setup that used to be schema.sql's CREATE INDEX
    statements."""

    def __init__(self, uri: str, db_name: str) -> None:
        self.uri = uri
        self.db_name = db_name
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None

    async def connect(self) -> None:
        if self._client is not None:
            return
        # serverSelectionTimeoutMS keeps a bad URI/network issue from hanging
        # the bot's startup indefinitely -- fails fast with a clear error
        # instead. tz_aware makes datetimes returned by Motor timezone-aware
        # (UTC), matching how the rest of the app already reasons about time.
        self._client = AsyncIOMotorClient(
            self.uri, serverSelectionTimeoutMS=15000, tz_aware=True
        )
        self._db = self._client[self.db_name]
        # Fails fast on a bad connection string / network issue / auth
        # problem, rather than only discovering it on the first real query
        # deep inside a repository call.
        await self._client.admin.command("ping")
        await self._ensure_indexes()
        logger.info("Database connected: MongoDB Atlas (db=%s)", self.db_name)

    async def _ensure_indexes(self) -> None:
        """Equivalent of schema.sql's CREATE INDEX / UNIQUE constraints.
        create_index is idempotent (a no-op if the index already exists
        with the same spec), so this is safe to run on every startup --
        same pattern as the old executescript(schema.sql) call."""
        assert self._db is not None
        db = self._db

        await db.users.create_index("chat_id", unique=True)
        await db.users.create_index([("is_premium", 1), ("premium_until", 1)])

        await db.quizzes.create_index("qid", unique=True)
        await db.quizzes.create_index("creator_id")
        await db.quizzes.create_index("quiz_name")
        await db.quizzes.create_index("search_indexed")

        await db.auth_chats.create_index("creator_id", unique=True)

        await db.payments.create_index("user_id")
        await db.payments.create_index("transaction_id")

        await db.ai_keys.create_index([("user_id", 1), ("provider", 1)])

        await db.quiz_attempts.create_index("attempt_id", unique=True)
        await db.quiz_attempts.create_index("user_id")
        await db.quiz_attempts.create_index("qid")

        await db.leaderboard.create_index([("qid", 1), ("user_id", 1)], unique=True)
        await db.leaderboard.create_index([("qid", 1), ("score", -1), ("time_taken", 1)])

        await db.question_wrong_stats.create_index([("qid", 1), ("q_index", 1)], unique=True)

        await db.user_mistakes.create_index(
            [("user_id", 1), ("qid", 1), ("q_index", 1)], unique=True
        )
        await db.user_mistakes.create_index("user_id")

        await db.creator_settings.create_index("user_id", unique=True)
        await db.chat_settings.create_index("chat_id", unique=True)
        await db.user_quiz_prefs.create_index("chat_id", unique=True)

        await db.batches.create_index("batch_id", unique=True)
        await db.batches.create_index("creator_id")
        await db.batch_access.create_index([("batch_id", 1), ("chat_id", 1)], unique=True)
        await db.batch_quizzes.create_index([("batch_id", 1), ("qid", 1)], unique=True)

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("Database connection closed")

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    def collection(self, name: str) -> AsyncIOMotorCollection:
        return self.db[name]


_db_instance: Optional[Database] = None


def get_db() -> Database:
    """Return the process-wide Database singleton (must call init_db() first)."""
    if _db_instance is None:
        raise RuntimeError("Database not initialized. Call init_db(...) at startup.")
    return _db_instance


async def init_db(uri: str, db_name: str = "quizbot") -> Database:
    """Create (if needed) and connect the shared database. Idempotent per-process."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(uri, db_name)
    await _db_instance.connect()
    return _db_instance


async def close_db() -> None:
    global _db_instance
    if _db_instance is not None:
        await _db_instance.close()
        _db_instance = None
