"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any, Optional

from quizbot.shared import config


class SessionManager:
    """Active-quiz session state, keyed by chat_id.

    Reads are lock-free (safe under the single-threaded asyncio event loop);
    writes take a lock so concurrent updates from different tasks (poll
    timeouts, poll-answer handlers, the quiz-runner loop) don't interleave.
    """

    def __init__(self) -> None:
        self.sessions: dict[int, dict[str, Any]] = {}
        self._activity: dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def create(self, chat_id: int, data: dict[str, Any]) -> None:
        async with self._lock:
            self.sessions[chat_id] = data
            self._activity[chat_id] = time.time()

    def get(self, chat_id: int) -> Optional[dict[str, Any]]:
        """Lock-free read -- safe because of the GIL + single event loop."""
        s = self.sessions.get(chat_id)
        if s is not None:
            self._activity[chat_id] = time.time()
        return s

    async def update(self, chat_id: int, updates: dict[str, Any]) -> None:
        async with self._lock:
            if chat_id in self.sessions:
                self.sessions[chat_id].update(updates)
                self._activity[chat_id] = time.time()

    async def delete(self, chat_id: int) -> Optional[dict[str, Any]]:
        async with self._lock:
            self._activity.pop(chat_id, None)
            return self.sessions.pop(chat_id, None)

    async def cleanup(self) -> None:
        """Drop sessions with no activity for longer than SESSION_TIMEOUT."""
        async with self._lock:
            now = time.time()
            dead = [
                cid for cid, t in self._activity.items()
                if now - t > config.SESSION_TIMEOUT
            ]
            for cid in dead:
                self.sessions.pop(cid, None)
                self._activity.pop(cid, None)

    def active_count(self) -> int:
        return len(self.sessions)


session_mgr = SessionManager()


class RateLimiter:
    """Simple sliding-window rate limiter, one bucket per user."""

    def __init__(self) -> None:
        self.buckets: dict[int, deque] = defaultdict(
            lambda: deque(maxlen=config.RATE_LIMIT_MAX_REQUESTS)
        )

    async def check(self, user_id: int) -> bool:
        now = time.time()
        bucket = self.buckets[user_id]
        while bucket and bucket[0] < now - config.RATE_LIMIT_WINDOW:
            bucket.popleft()
        if len(bucket) >= config.RATE_LIMIT_MAX_REQUESTS:
            return False
        bucket.append(now)
        return True

    def cleanup(self) -> None:
        now = time.time()
        dead = [
            uid for uid, b in self.buckets.items()
            if not b or b[-1] < now - config.RATE_LIMIT_WINDOW
        ]
        for uid in dead:
            del self.buckets[uid]


rate_limiter = RateLimiter()


class TaskTracker:
    """Keeps strong references to all spawned asyncio tasks so they are
    never garbage-collected mid-flight, and logs exceptions instead of
    silently swallowing them (no fire-and-forget tasks anywhere)."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._counter = 0

    def spawn(self, coro, name: str = "") -> asyncio.Task:
        self._counter += 1
        task_id = f"{name}_{self._counter}" if name else f"task_{self._counter}"
        task = asyncio.create_task(coro, name=task_id)
        self._tasks[task_id] = task
        task.add_done_callback(lambda t: self._on_done(task_id, t))
        return task

    def _on_done(self, task_id: str, task: asyncio.Task) -> None:
        import logging

        self._tasks.pop(task_id, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logging.getLogger(__name__).error("Task %s crashed: %s", task_id, exc, exc_info=exc)

    def active_count(self) -> int:
        return len(self._tasks)

    def cancel_all_for_chat(self, chat_id: int) -> None:
        prefix = f"quiz_{chat_id}_"
        for task_id, task in list(self._tasks.items()):
            if prefix in task_id and not task.done():
                task.cancel()


tasks = TaskTracker()

# chat_id -> asyncio.Task for an ongoing channel /pollquiz run.
channel_poll_tasks: dict[int, asyncio.Task] = {}

# Pending quiz-setup wizard state (before a quiz begins), keyed by chat_id.
# See handlers/setup_wizard.py for the qs_* callback flow that populates this.
pending_quiz_settings: dict[int, dict[str, Any]] = {}

# /aiquiz wizard state, keyed by the initiating user's id.
AI_QUIZ_SESSIONS: dict[int, dict[str, Any]] = {}

# /pdfquiz wizard state, keyed by the initiating user's id.
PDF_QUIZ_SESSIONS: dict[int, dict[str, Any]] = {}


class TranslationManager:
    """Per-chat active translation language for /trans."""

    def __init__(self) -> None:
        self.settings: dict[int, Optional[str]] = {}

    def get_language(self, chat_id: int) -> Optional[str]:
        return self.settings.get(chat_id)

    def set_language(self, chat_id: int, lang: Optional[str]) -> None:
        if lang:
            self.settings[chat_id] = lang
        else:
            self.settings.pop(chat_id, None)


translation_mgr = TranslationManager()

# Cache of the last AI provider+key that worked per user, so /aiquiz and
# /pdfquiz chunked generation doesn't re-probe every provider on each chunk.
# user_id -> {"provider": str, "key_id": int|None, "api_key": str}
last_working_ai: dict[int, dict[str, Any]] = {}
