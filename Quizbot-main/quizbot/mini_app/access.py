"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from quizbot.database import AuthChatRepository, BatchRepository, UserRepository, get_db
from quizbot.shared.utils import is_premium_user


@dataclass
class AccessResult:
    allowed: bool
    reason: str = ""
    batch: Optional[dict] = None


async def check_play_access(quiz: dict, user_id: int) -> AccessResult:
    """Decide whether `user_id` may play `quiz` in the Mini App.

    Rules (matching the bots' own access logic):
      - Free quizzes: anyone may play.
      - Paid quizzes: allowed if the player is the quiz's own creator, or
        their user_id is in the creator's `auth_chats` list, or they have
        batch access to this specific quiz.
    """
    if quiz.get("quiz_type") != "paid":
        return AccessResult(allowed=True)

    creator_id = quiz.get("creator_id")
    if creator_id == user_id:
        return AccessResult(allowed=True)

    auth_repo = AuthChatRepository(get_db())
    auth_users = await auth_repo.get(creator_id)
    if user_id in auth_users:
        return AccessResult(allowed=True)

    batch_repo = BatchRepository(get_db())
    has_access = await batch_repo.check_access(quiz["qid"], user_id)
    if has_access:
        return AccessResult(allowed=True)

    batch = await batch_repo.info_for_quiz(quiz["qid"])
    return AccessResult(
        allowed=False,
        reason="paid_quiz_no_access",
        batch=batch,
    )


async def check_premium_gate(user_id: int, require_premium: bool) -> AccessResult:
    """Some deployments may want to gate the Mini App itself behind premium
    (independent of individual quiz pricing). Off by default -- controlled
    by the caller, not hardcoded here."""
    if not require_premium:
        return AccessResult(allowed=True)
    if await is_premium_user(user_id):
        return AccessResult(allowed=True)
    return AccessResult(allowed=False, reason="premium_required")
