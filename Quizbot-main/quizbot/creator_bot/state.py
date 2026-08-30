"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from quizbot.shared import config


class SessionStore:
    """Generic per-user in-memory session dict with dict-like convenience
    methods. Wraps a single concern (quiz creation, edit sessions, ...).
    """

    def __init__(self) -> None:
        self._data: dict[int, dict[str, Any]] = {}

    def __contains__(self, uid: int) -> bool:
        return uid in self._data

    def get(self, uid: int, default: Any = None) -> Any:
        return self._data.get(uid, default)

    def __getitem__(self, uid: int) -> dict[str, Any]:
        return self._data[uid]

    def __setitem__(self, uid: int, value: dict[str, Any]) -> None:
        self._data[uid] = value

    def pop(self, uid: int, default: Any = None) -> Any:
        return self._data.pop(uid, default)

    def setdefault(self, uid: int, value: dict[str, Any]) -> dict[str, Any]:
        return self._data.setdefault(uid, value)

    def __len__(self) -> int:
        return len(self._data)


# ─── Quiz-creation wizard (/create ... /done) ────────────────────────────
# uid -> {questions: [...], quiz_name, timer, awaiting_*, sections, ...}
quiz_creation = SessionStore()

# ─── Quiz-editor wizard (/edit) ──────────────────────────────────────────
# uid -> {qid, page, field, stg_field, q_idx, pending_delete, ...}
edit_sessions = SessionStore()

# ─── Batch-creation / batch-edit wizard (/createbatch, /batch callbacks) ─
# uid -> {step, bid, name, desc, contact, payment, _pending_qid, ...}
batch_sessions = SessionStore()

# ─── Global quiz-search pagination state (/search) ───────────────────────
# uid -> {term, results}
search_state = SessionStore()

# ─── Pending Razorpay payments awaiting the /start?pay_<token> callback ──
# token -> {uid, days, plan_label, price, link_id, expires_at}
pending_payments: dict[str, dict[str, Any]] = {}

# ─── Per-user quiz list cache (used by pagination callbacks) ─────────────
# uid -> {"data": [...], "timestamp": float}
_quiz_list_cache: dict[int, dict[str, Any]] = {}


def save_quiz_list_cache(uid: int, quizzes: list[dict]) -> None:
    _quiz_list_cache[uid] = {"data": quizzes, "timestamp": time.time()}


def load_quiz_list_cache(uid: int) -> Optional[dict]:
    entry = _quiz_list_cache.get(uid)
    if entry is None:
        return None
    if time.time() - entry["timestamp"] > config.CACHE_EXPIRY:
        _quiz_list_cache.pop(uid, None)
        return None
    return entry


def clear_quiz_list_cache(uid: int) -> None:
    _quiz_list_cache.pop(uid, None)


# ─── Rate limiting ────────────────────────────────────────────────────────
# Sliding-window limiter, three buckets matching the original bot exactly:
#   "default" -- most commands            (10 hits / 30 min)
#   "create"  -- /create + /done (heavier, DB-writing flow) (4 hits / 30 min)
#   "strict"  -- the heaviest commands (/myquizzes, /edit)  (1 hit / 60 min)
# Each bucket is independently operator-tunable via its own CREATOR_RATE_LIMIT_*
# env var (see shared/config.py) -- these are NOT derived from the Runner
# Bot's generic RATE_LIMIT_WINDOW/MAX_REQUESTS knob, which has different
# defaults suited to a different bot.
RATE_LIMIT_BUCKETS: dict[str, tuple[int, int]] = {
    "default": config.CREATOR_RATE_LIMIT_DEFAULT,
    "create": config.CREATOR_RATE_LIMIT_CREATE,
    "strict": config.CREATOR_RATE_LIMIT_STRICT,
}

_rl_hits: dict[int, dict[str, list[float]]] = {}
_rl_warned: dict[int, dict[str, bool]] = {}


def _prune(times: list[float], window: int) -> None:
    cutoff = time.time() - window
    while times and times[0] < cutoff:
        times.pop(0)


def check_rate_limit(user_id: int, bucket: str = "default") -> Optional[int]:
    """Record a hit for `user_id` in `bucket`. Returns None if allowed, or
    the number of minutes until the window resets if the limit was hit.
    Only returns a non-None value the *first* time the limit is crossed for
    the current window (matches original "warn once" UX) -- subsequent
    calls while still over the limit return -1 to signal "already warned,
    stay silent".
    """
    limit, window = RATE_LIMIT_BUCKETS[bucket]
    hits = _rl_hits.setdefault(user_id, {}).setdefault(bucket, [])
    warned = _rl_warned.setdefault(user_id, {})
    _prune(hits, window)
    if len(hits) >= limit:
        if not warned.get(bucket):
            warned[bucket] = True
            mins = max(1, int((window - (time.time() - hits[0])) / 60))
            return mins
        return -1
    hits.append(time.time())
    warned[bucket] = False
    return None


def rate_limit_status_text(user_id: int) -> str:
    """Human-readable summary of the user's current rate-limit usage,
    used by /limit."""
    labels = {
        "default": "General commands",
        "create": "/create + /done",
        "strict": "Heavier commands (/myquizzes, /edit)",
    }
    lines = ["Your command limits:\n"]
    for bucket, (limit, window) in RATE_LIMIT_BUCKETS.items():
        hits = _rl_hits.get(user_id, {}).get(bucket, [])
        _prune(hits, window)
        used = len(hits)
        remaining = max(0, limit - used)
        window_min = max(1, window // 60)
        label = f"{labels[bucket]} ({limit} / {window_min} min)"
        if used >= limit and hits:
            reset_in = max(1, int((window - (time.time() - hits[0])) / 60))
            lines.append(f"- {label}: {used}/{limit} used, resets in ~{reset_in} min")
        else:
            lines.append(f"- {label}: {used}/{limit} used, {remaining} left")
    return "\n".join(lines)


# ─── Broadcast (/gcast) control flag ─────────────────────────────────────
class BroadcastControl:
    """Tiny mutable flag object so /stopcast can interrupt a running
    /gcast loop without relying on a bare module global."""

    def __init__(self) -> None:
        self.active = False


broadcast = BroadcastControl()
