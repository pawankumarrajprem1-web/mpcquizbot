"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .db import Database


def _now_iso() -> str:
    """Kept as a plain ISO-format string (not a native datetime) so every
    existing `datetime.strptime(row["...at"], "%Y-%m-%d %H:%M:%S")` call
    elsewhere in the codebase (there are a few, e.g. AttemptRepository's
    own elapsed-time math below, and is_premium's expiry check) keeps
    working unmodified -- storing a plain string field in Mongo is just as
    natural as storing one in a SQLite TEXT column."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _clean(doc: Optional[dict]) -> Optional[dict]:
    """Strip Mongo's own `_id` (an ObjectId, not JSON/caller-friendly) from
    a document before handing it back to a caller. Every collection has its
    own business-key field (qid, attempt_id, chat_id, ...) that callers
    already use instead, so `_id` itself is never meaningful to them."""
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


class UserRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("users")

    async def get_or_create(self, chat_id: int) -> dict:
        row = await self.col.find_one({"chat_id": chat_id})
        if row is None:
            doc = {
                "chat_id": chat_id,
                "remove_words": [],
                "is_premium": False,
                "premium_until": None,
                "language": "en",
                "created_at": _now_iso(),
                "last_active": _now_iso(),
            }
            await self.col.insert_one(doc)
            row = doc
        else:
            await self.col.update_one(
                {"chat_id": chat_id}, {"$set": {"last_active": _now_iso()}}
            )
            row["last_active"] = _now_iso()
        return _clean(row)

    async def get(self, chat_id: int) -> Optional[dict]:
        row = await self.col.find_one({"chat_id": chat_id})
        return _clean(row)

    async def get_all(self, limit: int = 1000, offset: int = 0) -> list[dict]:
        cursor = self.col.find().sort("_id", -1).skip(offset).limit(limit)
        return [_clean(r) async for r in cursor]

    async def update_remove_words(self, chat_id: int, remove_words: list[str]) -> None:
        await self.get_or_create(chat_id)
        await self.col.update_one(
            {"chat_id": chat_id}, {"$set": {"remove_words": remove_words}}
        )

    async def is_premium(self, chat_id: int) -> bool:
        row = await self.col.find_one(
            {"chat_id": chat_id}, {"is_premium": 1, "premium_until": 1}
        )
        if row is None or not row.get("is_premium"):
            return False
        if row.get("premium_until") is None:
            return True  # permanent premium
        try:
            expiry = datetime.strptime(row["premium_until"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return False
        return expiry > datetime.now(timezone.utc)

    async def set_premium(self, chat_id: int, days: Optional[int] = 30) -> None:
        await self.get_or_create(chat_id)
        premium_until = None
        if days is not None:
            premium_until = (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        await self.col.update_one(
            {"chat_id": chat_id},
            {"$set": {"is_premium": True, "premium_until": premium_until}},
        )

    async def revoke_premium(self, chat_id: int) -> None:
        await self.col.update_one(
            {"chat_id": chat_id}, {"$set": {"is_premium": False, "premium_until": None}}
        )

    async def list_active_premium(self) -> list[dict]:
        """Every user currently on active premium (permanent or unexpired),
        ordered by expiry -- mirrors the original PHP `PremiumAPI::getAllPremium`."""
        cursor = self.col.find(
            {
                "is_premium": True,
                "$or": [{"premium_until": None}, {"premium_until": {"$gt": _now_iso()}}],
            }
        ).sort([("premium_until", 1)])
        # Mongo's ascending sort already puts None values first (BSON type
        # ordering: Null < String), matching the old
        # "ORDER BY premium_until IS NULL, premium_until ASC" exactly.
        return [_clean(r) async for r in cursor]

    async def stats(self) -> dict:
        total = await self.col.count_documents({})
        premium = await self.col.count_documents(
            {
                "is_premium": True,
                "$or": [{"premium_until": None}, {"premium_until": {"$gt": _now_iso()}}],
            }
        )
        return {"total_users": total, "premium_users": premium}


class QuizRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("quizzes")

    @staticmethod
    def _new_qid() -> str:
        return uuid.uuid4().hex[:10]

    async def create(self, creator_id: int, quiz_name: str, questions: list[dict], **kwargs) -> dict:
        qid = kwargs.get("qid") or self._new_qid()
        doc = {
            "qid": qid,
            "creator_id": creator_id,
            "quiz_name": quiz_name,
            "questions": questions,
            "sections": kwargs.get("sections", []),
            "timer": kwargs.get("timer", 60),
            "quiz_type": kwargs.get("quiz_type", "free"),
            "negative_marks": kwargs.get("negative_marks", 0),
            "correct_marks": kwargs.get("correct_marks", 1),
            "shuffle_questions": bool(kwargs.get("shuffle_questions", False)),
            "shuffle_options": bool(kwargs.get("shuffle_options", False)),
            "edit_permissions": [],
            "promo_message": kwargs.get("promo_message"),
            "search_indexed": True,
            "total_participants": 0,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await self.col.insert_one(doc)
        return await self.get(qid)

    async def get(self, qid: str) -> Optional[dict]:
        row = await self.col.find_one({"qid": qid})
        return _clean(row)

    async def update_field(self, qid: str, field: str, value: Any) -> None:
        allowed = {
            "quiz_name", "questions", "sections", "timer", "quiz_type",
            "negative_marks", "correct_marks", "shuffle_questions", "shuffle_options",
            "edit_permissions", "promo_message", "search_indexed",
        }
        if field not in allowed:
            raise ValueError(f"Field '{field}' is not updatable")
        await self.col.update_one(
            {"qid": qid}, {"$set": {field: value, "updated_at": _now_iso()}}
        )

    async def delete(self, qid: str) -> None:
        await self.col.delete_one({"qid": qid})

    async def list_by_creator(self, creator_id: int, query: Optional[str] = None) -> list[dict]:
        filt: dict = {"creator_id": creator_id}
        if query:
            filt["quiz_name"] = {"$regex": _escape_regex(query), "$options": "i"}
        cursor = self.col.find(filt).sort("created_at", -1)
        return [self._light(r) async for r in cursor]

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[dict]:
        cursor = self.col.find().sort("created_at", -1).skip(offset).limit(limit)
        return [self._light(r) async for r in cursor]

    async def search(self, query: str, limit: int = 20, offset: int = 0) -> list[dict]:
        """Search publicly-indexed quizzes by name, newest-plays-first.

        Excludes a quiz both when its own `search_indexed` flag is off AND
        when its creator has since turned OFF "Search Index" in /settings
        (creator_settings.search_indexed) -- the latter is a live,
        retroactive opt-out: flipping it off in /settings immediately pulls
        every quiz that creator owns out of /search, not just future ones.
        Supports offset-based pagination so /search isn't capped at
        whatever `limit` the first page used -- callers can page through
        the full result set with repeated calls."""
        pattern = _escape_regex(query)
        pipeline = [
            {"$match": {"search_indexed": True, "quiz_name": {"$regex": pattern, "$options": "i"}}},
            {
                "$lookup": {
                    "from": "creator_settings",
                    "localField": "creator_id",
                    "foreignField": "user_id",
                    "as": "_creator_settings",
                }
            },
            {
                "$match": {
                    "$or": [
                        {"_creator_settings": {"$size": 0}},  # no settings row yet -> defaults to indexed
                        {"_creator_settings.0.search_indexed": {"$ne": False}},
                    ]
                }
            },
            {"$project": {"_creator_settings": 0}},
            {"$sort": {"total_participants": -1}},
            {"$skip": offset},
            {"$limit": limit},
        ]
        rows = [r async for r in self.col.aggregate(pipeline)]
        return [self._light(r) for r in rows]

    async def search_count(self, query: str) -> int:
        """Total number of quizzes /search would match for `query`, ignoring
        limit/offset -- used to show accurate "X of Y" / enable "Load more"
        without capping the searchable set."""
        pattern = _escape_regex(query)
        pipeline = [
            {"$match": {"search_indexed": True, "quiz_name": {"$regex": pattern, "$options": "i"}}},
            {
                "$lookup": {
                    "from": "creator_settings",
                    "localField": "creator_id",
                    "foreignField": "user_id",
                    "as": "_creator_settings",
                }
            },
            {
                "$match": {
                    "$or": [
                        {"_creator_settings": {"$size": 0}},
                        {"_creator_settings.0.search_indexed": {"$ne": False}},
                    ]
                }
            },
            {"$count": "n"},
        ]
        rows = [r async for r in self.col.aggregate(pipeline)]
        return rows[0]["n"] if rows else 0

    async def set_promo_for_creator(self, creator_id: int, promo_message: str) -> int:
        result = await self.col.update_many(
            {"creator_id": creator_id},
            {"$set": {"promo_message": promo_message, "updated_at": _now_iso()}},
        )
        return result.modified_count

    async def reassign_owner(self, old_creator_id: int, new_creator_id: int) -> None:
        await self.col.update_many(
            {"creator_id": old_creator_id}, {"$set": {"creator_id": new_creator_id}}
        )
        await self.db.collection("batches").update_many(
            {"creator_id": old_creator_id}, {"$set": {"creator_id": new_creator_id}}
        )
        await self.db.collection("auth_chats").update_many(
            {"creator_id": old_creator_id}, {"$set": {"creator_id": new_creator_id}}
        )

    async def increment_participants(self, qid: str) -> None:
        await self.col.update_one({"qid": qid}, {"$inc": {"total_participants": 1}})

    async def stats(self) -> dict:
        total = await self.col.count_documents({})
        paid = await self.col.count_documents({"quiz_type": "paid"})
        free = await self.col.count_documents({"quiz_type": "free"})
        return {"total_quizzes": total, "paid_quizzes": paid, "free_quizzes": free}

    @staticmethod
    def _light(row: dict) -> dict:
        """Metadata only -- omit heavy `questions`/`sections` blobs for list views."""
        data = _clean(row)
        data.pop("questions", None)
        data.pop("sections", None)
        return data


class AuthChatRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("auth_chats")

    async def get(self, creator_id: int) -> list[int]:
        row = await self.col.find_one({"creator_id": creator_id})
        return row.get("auth_users", []) if row else []

    async def set(self, creator_id: int, auth_users: list[int]) -> None:
        await self.col.update_one(
            {"creator_id": creator_id},
            {
                "$set": {"auth_users": auth_users},
                "$setOnInsert": {"created_at": _now_iso()},
            },
            upsert=True,
        )

    async def add(self, creator_id: int, chat_id: int) -> list[int]:
        users = await self.get(creator_id)
        if chat_id not in users:
            users.append(chat_id)
            await self.set(creator_id, users)
        return users

    async def remove(self, creator_id: int, chat_id: int) -> list[int]:
        users = await self.get(creator_id)
        if chat_id in users:
            users.remove(chat_id)
            await self.set(creator_id, users)
        return users

    async def clear(self, creator_id: int) -> None:
        await self.set(creator_id, [])


class PaymentRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("payments")

    async def create(self, user_id: int, amount: int, plan_days: Optional[int] = None) -> dict:
        doc = {
            "user_id": user_id,
            "amount": amount,
            "status": "created",
            "payment_method": None,
            "transaction_id": None,
            "plan_days": plan_days,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        result = await self.col.insert_one(doc)
        row = await self.col.find_one({"_id": result.inserted_id})
        return _clean(row)

    async def get_for_user(self, user_id: int) -> list[dict]:
        cursor = self.col.find({"user_id": user_id}).sort("created_at", -1)
        return [_clean(r) async for r in cursor]

    async def update_latest_status(
        self, user_id: int, status: str, transaction_id: Optional[str] = None
    ) -> Optional[dict]:
        row = await self.col.find_one({"user_id": user_id}, sort=[("created_at", -1)])
        if row is None:
            return None
        await self.col.update_one(
            {"_id": row["_id"]},
            {"$set": {"status": status, "transaction_id": transaction_id, "updated_at": _now_iso()}},
        )
        updated = await self.col.find_one({"_id": row["_id"]})
        return _clean(updated)


def _clean_key(doc: Optional[dict]) -> Optional[dict]:
    """Like _clean(), but keeps the Mongo _id around as a plain string "id"
    field -- callers (ai_keys.py, ai_providers.py) display/round-trip this
    the same way they used to display SQLite's autoincrement `id` column."""
    if doc is None:
        return None
    doc = dict(doc)
    oid = doc.pop("_id", None)
    if oid is not None:
        doc["id"] = str(oid)
    return doc


class AIKeyRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("ai_keys")

    async def list_for_user(self, user_id: int) -> list[dict]:
        cursor = self.col.find({"user_id": user_id}).sort("created_at", 1)
        return [_clean_key(r) async for r in cursor]

    async def list_for_provider(self, user_id: int, provider: str) -> list[dict]:
        cursor = self.col.find({"user_id": user_id, "provider": provider}).sort(
            [("fail_count", 1), ("created_at", 1)]
        )
        return [_clean_key(r) async for r in cursor]

    async def add(self, user_id: int, provider: str, api_key: str, label: Optional[str] = None) -> dict:
        doc = {
            "user_id": user_id,
            "provider": provider,
            "api_key": api_key,
            "label": label,
            "last_used_at": None,
            "fail_count": 0,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        result = await self.col.insert_one(doc)
        row = await self.col.find_one({"_id": result.inserted_id})
        return _clean_key(row)

    async def mark(self, key_id: Any, failed: bool) -> None:
        oid = _as_object_id(key_id)
        if failed:
            await self.col.update_one(
                {"_id": oid}, {"$inc": {"fail_count": 1}, "$set": {"updated_at": _now_iso()}}
            )
        else:
            await self.col.update_one(
                {"_id": oid},
                {"$set": {"last_used_at": _now_iso(), "fail_count": 0, "updated_at": _now_iso()}},
            )

    async def delete_by_id(self, user_id: int, key_id: Any) -> None:
        await self.col.delete_one({"_id": _as_object_id(key_id), "user_id": user_id})

    async def delete_by_provider(self, user_id: int, provider: str) -> None:
        await self.col.delete_many({"user_id": user_id, "provider": provider})

    async def delete_all(self, user_id: int) -> None:
        await self.col.delete_many({"user_id": user_id})


class AttemptRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("quiz_attempts")

    async def start(self, user_id: int, qid: str, quiz_name: str, total_questions: int) -> dict:
        attempt_id = uuid.uuid4().hex
        doc = {
            "attempt_id": attempt_id,
            "user_id": user_id,
            "qid": qid,
            "quiz_name": quiz_name,
            "current_question": 0,
            "answers": {},
            "score": 0,
            "total_questions": total_questions,
            "time_started": _now_iso(),
            "time_ended": None,
            "status": "in_progress",
            "paused": False,
            "pause_time": None,
            "total_pause_duration": 0,
        }
        await self.col.insert_one(doc)
        return await self.get(attempt_id)

    async def get(self, attempt_id: str) -> Optional[dict]:
        row = await self.col.find_one({"attempt_id": attempt_id})
        return _clean(row)

    async def update(self, attempt_id: str, **fields) -> None:
        allowed = {"current_question", "answers", "score", "paused"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        await self.col.update_one({"attempt_id": attempt_id}, {"$set": sets})

    async def pause(self, attempt_id: str, pause: bool) -> None:
        if pause:
            await self.col.update_one(
                {"attempt_id": attempt_id},
                {"$set": {"paused": True, "pause_time": _now_iso()}},
            )
        else:
            attempt = await self.get(attempt_id)
            if attempt and attempt.get("pause_time"):
                started = datetime.strptime(attempt["pause_time"], "%Y-%m-%d %H:%M:%S")
                elapsed = int((datetime.now(timezone.utc).replace(tzinfo=None) - started).total_seconds())
                await self.col.update_one(
                    {"attempt_id": attempt_id},
                    {
                        "$set": {"paused": False, "pause_time": None},
                        "$inc": {"total_pause_duration": max(elapsed, 0)},
                    },
                )
            else:
                await self.col.update_one(
                    {"attempt_id": attempt_id},
                    {"$set": {"paused": False, "pause_time": None}},
                )

    async def complete(self, attempt_id: str, score: int, username: str) -> Optional[dict]:
        attempt = await self.get(attempt_id)
        if attempt is None:
            return None
        await self.col.update_one(
            {"attempt_id": attempt_id},
            {"$set": {"status": "completed", "score": score, "time_ended": _now_iso()}},
        )
        started = datetime.strptime(attempt["time_started"], "%Y-%m-%d %H:%M:%S")
        elapsed = int(
            (datetime.now(timezone.utc).replace(tzinfo=None) - started).total_seconds()
        ) - attempt.get("total_pause_duration", 0)
        try:
            # First-attempt-only leaderboard entry: a unique index on
            # (qid, user_id) makes a duplicate insert raise
            # DuplicateKeyError, same role SQLite's UNIQUE constraint +
            # swallowed exception played before.
            await self.db.collection("leaderboard").insert_one(
                {
                    "qid": attempt["qid"],
                    "user_id": attempt["user_id"],
                    "username": username,
                    "user_name": username,
                    "score": score,
                    "total_questions": attempt["total_questions"],
                    "time_taken": max(elapsed, 0),
                    "completed_at": _now_iso(),
                }
            )
        except Exception:
            pass  # unique(qid, user_id) -- first attempt only, ignore duplicates
        return await self.get(attempt_id)

    async def list_completed(self, qid: str) -> list[dict]:
        """All completed attempts for a quiz, newest first (by time_ended).
        Used for the /compare_results analysis report."""
        cursor = self.col.find({"qid": qid, "status": "completed"}).sort(
            "time_ended", -1
        )
        return [_clean(r) async for r in cursor]


class LeaderboardRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("leaderboard")

    async def top(self, qid: str, limit: int = 10) -> list[dict]:
        cursor = (
            self.col.find({"qid": qid})
            .sort([("score", -1), ("time_taken", 1)])
            .limit(limit)
        )
        return [_clean(r) async for r in cursor]

    async def page(self, qid: str, offset: int = 0, limit: int = 200) -> list[dict]:
        # Mongo's $setWindowFields (5.0+, fully supported on Atlas incl. the
        # free M0 tier) is the aggregation-pipeline equivalent of SQL's
        # RANK() OVER (...) window function used here previously.
        pipeline = [
            {"$match": {"qid": qid}},
            {"$sort": {"score": -1, "time_taken": 1}},
            {
                "$setWindowFields": {
                    "sortBy": {"score": -1, "time_taken": 1},
                    "output": {"rank": {"$rank": {}}},
                }
            },
            {"$skip": offset},
            {"$limit": limit},
        ]
        rows = [r async for r in self.col.aggregate(pipeline)]
        return [_clean(r) for r in rows]

    async def user_rank(self, qid: str, user_id: int) -> Optional[dict]:
        pipeline = [
            {"$match": {"qid": qid}},
            {
                "$setWindowFields": {
                    "sortBy": {"score": -1, "time_taken": 1},
                    "output": {"rank": {"$rank": {}}},
                }
            },
            {"$match": {"user_id": user_id}},
            {"$limit": 1},
        ]
        rows = [r async for r in self.col.aggregate(pipeline)]
        return _clean(rows[0]) if rows else None


class QuestionStatsRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("question_wrong_stats")

    async def bulk_update_wrong_stats(self, qid: str, items: list[dict]) -> None:
        for item in items:
            q_index = item["index"]
            existing = await self.col.find_one({"qid": qid, "q_index": q_index})
            if existing:
                wrong = existing["wrong_count"] + item.get("wrong", 0)
                total = existing["total_count"] + item.get("total", 1)
                is_hard = existing["is_hard"]
                flagged_at = existing["hard_flagged_at"]
                if not is_hard and total >= 50 and (wrong / total) >= 0.20:
                    is_hard, flagged_at = True, _now_iso()
                await self.col.update_one(
                    {"qid": qid, "q_index": q_index},
                    {
                        "$set": {
                            "wrong_count": wrong,
                            "total_count": total,
                            "is_hard": is_hard,
                            "hard_flagged_at": flagged_at,
                        }
                    },
                )
            else:
                wrong = item.get("wrong", 0)
                total = item.get("total", 1)
                is_hard = bool(total >= 50 and (wrong / total) >= 0.20)
                await self.col.insert_one(
                    {
                        "qid": qid,
                        "q_index": q_index,
                        "wrong_count": wrong,
                        "total_count": total,
                        "is_hard": is_hard,
                        "hard_flagged_at": _now_iso() if is_hard else None,
                    }
                )

    async def hard_questions(self, qid: str) -> list[dict]:
        cursor = self.col.find({"qid": qid, "is_hard": True})
        return [_clean(r) async for r in cursor]


class MistakeRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("user_mistakes")

    async def record(self, user_id: int, items: list[dict]) -> None:
        for item in items:
            existing = await self.col.find_one(
                {"user_id": user_id, "qid": item["qid"], "q_index": item["index"]}
            )
            if existing:
                await self.col.update_one(
                    {"_id": existing["_id"]},
                    {"$inc": {"wrong_count": 1}, "$set": {"last_wrong_at": _now_iso()}},
                )
            else:
                await self.col.insert_one(
                    {
                        "user_id": user_id,
                        "qid": item["qid"],
                        "q_index": item["index"],
                        "wrong_count": 1,
                        "last_wrong_at": _now_iso(),
                    }
                )

    async def list_for_user(self, user_id: int, limit: int = 20) -> list[dict]:
        cursor = (
            self.col.find({"user_id": user_id}).sort("last_wrong_at", -1).limit(limit)
        )
        return [_clean(r) async for r in cursor]

    async def resolve(self, user_id: int, qid: str, q_index: int) -> None:
        await self.col.delete_one({"user_id": user_id, "qid": qid, "q_index": q_index})


class CreatorSettingsRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("creator_settings")

    async def get(self, user_id: int) -> dict:
        row = await self.col.find_one({"user_id": user_id})
        if row is None:
            doc = {
                "user_id": user_id,
                "search_indexed": True,
                "default_text": None,
                "default_text_field": "both",
                "quiz_defaults": None,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            await self.col.insert_one(doc)
            row = doc
        return _clean(row)

    async def update(self, user_id: int, **fields) -> None:
        await self.get(user_id)
        allowed = {"search_indexed", "default_text", "default_text_field", "quiz_defaults"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        sets["updated_at"] = _now_iso()
        await self.col.update_one({"user_id": user_id}, {"$set": sets})


class ChatSettingsRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("chat_settings")

    async def get(self, chat_id: int) -> dict:
        row = await self.col.find_one({"chat_id": chat_id})
        if row is None:
            doc = {
                "chat_id": chat_id,
                "html_enabled": False,
                "pdf_enabled": False,
                "updated_at": _now_iso(),
            }
            await self.col.insert_one(doc)
            row = doc
        return _clean(row)

    async def get_all_enabled(self) -> list[dict]:
        """Every chat with HTML or PDF reports enabled -- used to warm an
        in-memory cache at startup instead of one query per chat (mirrors
        the original PHP `ChatSettingsAPI::getAllEnabled`)."""
        cursor = self.col.find({"$or": [{"html_enabled": True}, {"pdf_enabled": True}]})
        return [_clean(r) async for r in cursor]

    async def toggle(self, chat_id: int, which: str) -> bool:
        column = f"{which}_enabled"
        if column not in ("html_enabled", "pdf_enabled"):
            raise ValueError("which must be 'html' or 'pdf'")
        current = await self.get(chat_id)
        new_value = not current[column]
        await self.col.update_one(
            {"chat_id": chat_id}, {"$set": {column: new_value, "updated_at": _now_iso()}}
        )
        return new_value

    async def set(self, chat_id: int, which: str, enabled: bool) -> None:
        column = f"{which}_enabled"
        if column not in ("html_enabled", "pdf_enabled"):
            raise ValueError("which must be 'html' or 'pdf'")
        await self.get(chat_id)
        await self.col.update_one(
            {"chat_id": chat_id}, {"$set": {column: bool(enabled), "updated_at": _now_iso()}}
        )


class QuizPrefsRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("user_quiz_prefs")

    async def get(self, chat_id: int) -> dict:
        row = await self.col.find_one({"chat_id": chat_id})
        if row is None:
            doc = {
                "chat_id": chat_id,
                "correct_mark": 1,
                "neg_mark": 0,
                "shuffle_q": False,
                "shuffle_o": False,
                "shuffle_o_count": 0,
                "show_explanation": False,
                "anti_cheat": False,
                "timer_override": None,
                "updated_at": _now_iso(),
            }
            await self.col.insert_one(doc)
            row = doc
        return _clean(row)

    async def save(self, chat_id: int, **fields) -> None:
        await self.get(chat_id)
        allowed = {
            "correct_mark", "neg_mark", "shuffle_q", "shuffle_o", "shuffle_o_count",
            "show_explanation", "anti_cheat", "timer_override",
        }
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        sets["updated_at"] = _now_iso()
        await self.col.update_one({"chat_id": chat_id}, {"$set": sets})


class BatchRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col = db.collection("batches")
        self.access_col = db.collection("batch_access")
        self.quizzes_col = db.collection("batch_quizzes")

    @staticmethod
    def _new_batch_id() -> str:
        return uuid.uuid4().hex[:10]

    async def create(self, creator_id: int, name: str, **kwargs) -> dict:
        batch_id = self._new_batch_id()
        doc = {
            "batch_id": batch_id,
            "creator_id": creator_id,
            "name": name,
            "description": kwargs.get("description"),
            "contact_info": kwargs.get("contact_info"),
            "payment_link": kwargs.get("payment_link"),
            "created_at": _now_iso(),
        }
        await self.col.insert_one(doc)
        return await self.get(batch_id)

    async def get(self, batch_id: str) -> Optional[dict]:
        row = await self.col.find_one({"batch_id": batch_id})
        if row is None:
            return None
        data = _clean(row)
        data["chats"] = [
            r["chat_id"] async for r in self.access_col.find({"batch_id": batch_id})
        ]
        data["quizzes"] = [
            r["qid"] async for r in self.quizzes_col.find({"batch_id": batch_id})
        ]
        return data

    async def list_by_creator(self, creator_id: int) -> list[dict]:
        cursor = self.col.find({"creator_id": creator_id}).sort("created_at", -1)
        batch_ids = [r["batch_id"] async for r in cursor]
        return [await self.get(bid) for bid in batch_ids]

    async def update(self, batch_id: str, **fields) -> None:
        allowed = {"name", "description", "contact_info", "payment_link"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        await self.col.update_one({"batch_id": batch_id}, {"$set": sets})

    async def delete(self, batch_id: str) -> None:
        await self.col.delete_one({"batch_id": batch_id})
        # Mirrors the old schema's ON DELETE CASCADE on batch_access /
        # batch_quizzes -- Mongo has no native FK cascade, so it's done
        # explicitly here.
        await self.access_col.delete_many({"batch_id": batch_id})
        await self.quizzes_col.delete_many({"batch_id": batch_id})

    async def add_chat(self, batch_id: str, chat_id: int) -> None:
        await self.access_col.update_one(
            {"batch_id": batch_id, "chat_id": chat_id},
            {"$setOnInsert": {"batch_id": batch_id, "chat_id": chat_id}},
            upsert=True,
        )

    async def remove_chat(self, batch_id: str, chat_id: int) -> None:
        await self.access_col.delete_one({"batch_id": batch_id, "chat_id": chat_id})

    async def add_quiz(self, batch_id: str, qid: str) -> None:
        await self.quizzes_col.update_one(
            {"batch_id": batch_id, "qid": qid},
            {"$setOnInsert": {"batch_id": batch_id, "qid": qid}},
            upsert=True,
        )

    async def remove_quiz(self, batch_id: str, qid: str) -> None:
        await self.quizzes_col.delete_one({"batch_id": batch_id, "qid": qid})

    async def check_access(self, qid: str, chat_id: int) -> bool:
        bq = await self.quizzes_col.find_one({"qid": qid})
        if bq is None:
            return False
        row = await self.access_col.find_one({"batch_id": bq["batch_id"], "chat_id": chat_id})
        return row is not None

    async def info_for_quiz(self, qid: str) -> Optional[dict]:
        bq = await self.quizzes_col.find_one({"qid": qid})
        if bq is None:
            return None
        row = await self.col.find_one({"batch_id": bq["batch_id"]})
        return _clean(row)

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search batches by name OR description (matches the original PHP
        `BatchAPI::search`, which searched both fields)."""
        pattern = _escape_regex(query)
        cursor = (
            self.col.find(
                {
                    "$or": [
                        {"name": {"$regex": pattern, "$options": "i"}},
                        {"description": {"$regex": pattern, "$options": "i"}},
                    ]
                }
            )
            .sort("created_at", -1)
            .limit(limit)
        )
        return [_clean(r) async for r in cursor]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _escape_regex(text: str) -> str:
    """Escape regex metacharacters in user-supplied search text before using
    it in a Mongo $regex filter -- the SQL version's `LIKE ?` with a `%...%`
    wildcard had no equivalent injection risk since LIKE patterns aren't
    Python/regex syntax, but a raw string dropped into $regex here could
    let a search term with regex metacharacters (e.g. `.*`, `(`, `|`) behave
    unexpectedly or (for pathological patterns) run slowly. re.escape keeps
    the search literal, matching LIKE's plain-substring behavior."""
    import re

    return re.escape(text)


def _as_object_id(value: Any):
    """AIKeyRepository.mark/delete_by_id are called elsewhere in the
    codebase with the `id` field from a row previously returned by
    list_for_user/add -- under Mongo that field is now an ObjectId already
    (ai_keys rows no longer have a separate integer `id`; see the
    migration note in this module's docstring). Accept either an ObjectId
    already, or something coercible to one (e.g. its string form), so a
    caller holding either representation keeps working."""
    from bson import ObjectId

    if isinstance(value, ObjectId):
        return value
    return ObjectId(str(value))
