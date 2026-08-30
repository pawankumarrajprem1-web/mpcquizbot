"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Optional

from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import ContextTypes

from .state import pending_quiz_settings, session_mgr

logger = logging.getLogger(__name__)

# Telegram API hard limits.
TG_QUESTION_MAX = 295
TG_OPTION_MAX = 100
TG_EXPLANATION_MAX = 200
TG_DESCRIPTION_MAX = 1024

# Soft thresholds that decide when full text overflows into a description /
# separate message instead of being truncated inline in the poll.
QUESTION_SOFT_LIMIT = 290
OPTION_SOFT_LIMIT = 100
EXPLANATION_TRIM = 200

MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.5
POLL_SEND_DELAY = 0.3


async def send_raw_api(ctx: ContextTypes.DEFAULT_TYPE, method: str, params: dict[str, Any]) -> Any:
    """Adapter used by `quizbot.shared.rich_quiz` to issue a raw Bot API call
    (e.g. ``sendRichMessage``, Bot API 10.1) that has no typed wrapper in
    python-telegram-bot yet. `chat_id` is passed inside `params` and pulled
    out here since PTB's `do_api_request` takes it via `api_kwargs`.
    """
    return await ctx.bot.do_api_request(method, api_kwargs=params)


def _get_topic_thread_id(chat_id: int) -> Optional[int]:
    """Return message_thread_id for chat_id from the active session or a
    pending setup wizard, or None."""
    s = session_mgr.get(chat_id)
    if s and s.get("message_thread_id"):
        return s["message_thread_id"]
    ps = pending_quiz_settings.get(chat_id)
    if ps and ps.get("message_thread_id"):
        return ps["message_thread_id"]
    return None


async def safe_send_message(
    ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs: Any
) -> Optional[Any]:
    """Send a message with retry on flood-control/timeout/network errors."""
    if "message_thread_id" not in kwargs:
        tid = _get_topic_thread_id(chat_id)
        if tid:
            kwargs["message_thread_id"] = tid
    for attempt in range(MAX_RETRIES):
        try:
            return await ctx.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + random.uniform(0.5, 2.0))
        except TimedOut:
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt) + random.random())
        except NetworkError:
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt) + random.random())
        except BadRequest as e:
            logger.error("BadRequest sending message to %s: %s", chat_id, e)
            return None
        except TelegramError as e:
            if "chat not found" in str(e).lower() or "bot was blocked" in str(e).lower():
                return None
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
        except Exception as e:
            logger.error("Unexpected send error: %s", e)
            return None
    logger.error("Failed to send message to %s after %d retries", chat_id, MAX_RETRIES)
    return None


async def safe_send_poll(
    ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, question: str, options: list[str], **kwargs: Any
) -> Optional[Any]:
    """Send a poll with retry on flood-control/timeout/network errors."""
    if "message_thread_id" not in kwargs:
        tid = _get_topic_thread_id(chat_id)
        if tid:
            kwargs["message_thread_id"] = tid
    for attempt in range(MAX_RETRIES):
        try:
            return await ctx.bot.send_poll(chat_id=chat_id, question=question, options=options, **kwargs)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + random.uniform(1.0, 3.0))
        except TimedOut:
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt) + random.random())
        except NetworkError:
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt) + random.random())
        except BadRequest as e:
            err_msg = str(e).lower()
            logger.error("BadRequest sending poll to %s: %s", chat_id, e)
            if "too long" in err_msg or "too short" in err_msg or "chat not found" in err_msg:
                return None
            await asyncio.sleep(RETRY_BASE_DELAY * (attempt + 1))
        except TelegramError as e:
            if "chat not found" in str(e).lower() or "not enough rights" in str(e).lower():
                logger.error("Cannot send poll to %s: %s", chat_id, e)
                return None
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
        except Exception as e:
            logger.error("Unexpected poll error: %s", e)
            return None
    logger.error("Failed to send poll to %s after %d retries", chat_id, MAX_RETRIES)
    return None


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def prepare_poll_data(
    question_text: str,
    options: list[str],
    correct_option_id: int,
    explanation: Optional[str],
    reply_text: Optional[str],
    question_index: int,
    total_questions: int,
) -> tuple[str, list[str], Optional[str], Optional[str], Optional[str]]:
    """Fit question/options/explanation/reply_text within Telegram's poll
    limits.

    Returns (poll_question, poll_options, poll_explanation, overflow_text, poll_description).

    Uses Telegram's poll `description` field (up to 1024 chars) for
    overflow content when possible; falls back to a separate plain message
    only if even the description would exceed 1024 chars.

    Rules:
      - multiline question -> poll stem is last line; full body in description/overflow
      - question > 290 chars -> full text goes to description/overflow, poll gets a placeholder
      - any option > 100 chars -> full options shown in description/overflow
      - explanation > 200 chars -> trimmed to 190 chars + "..."
    """
    prefix = f"[{question_index + 1}/{total_questions}] "
    is_multiline = "\n" in question_text.strip()

    if is_multiline:
        lines = [ln for ln in question_text.strip().split("\n") if ln.strip()]
        poll_stem = lines[-1].strip()
        full_body = question_text.strip()
    else:
        poll_stem = question_text
        full_body = question_text

    full_question = f"{prefix}{poll_stem}"

    question_too_long = len(full_question) > QUESTION_SOFT_LIMIT
    any_option_long = any(len(opt) > OPTION_SOFT_LIMIT for opt in options)
    needs_overflow = is_multiline or question_too_long or any_option_long

    if question_too_long or is_multiline:
        poll_question = f"{prefix}Choose the correct option"
    else:
        poll_question = full_question
    poll_question = _truncate(poll_question, TG_QUESTION_MAX)

    if any_option_long:
        poll_options = [f"Option {chr(65 + i)}" for i in range(len(options))]
    else:
        poll_options = [_truncate(opt, TG_OPTION_MAX) for opt in options]
    poll_options = [o if o else "—" for o in poll_options]

    poll_explanation = None
    if explanation:
        poll_explanation = (
            _truncate(explanation, EXPLANATION_TRIM) if len(explanation) > TG_EXPLANATION_MAX else explanation
        )

    desc_parts: list[str] = []
    if needs_overflow:
        desc_parts.append(f"Q{question_index + 1}/{total_questions}: {full_body}")
    if reply_text:
        desc_parts.append(f"\n\n\U0001F4DD {reply_text}" if desc_parts else f"\U0001F4DD {reply_text}")
    if any_option_long and needs_overflow:
        desc_parts.append("\n\nOptions:")
        for i, opt in enumerate(options):
            desc_parts.append(f"\n  {chr(65 + i)}) {opt}")

    if not desc_parts:
        return poll_question, poll_options, poll_explanation, None, None

    description_text = "".join(desc_parts)

    if len(description_text) <= TG_DESCRIPTION_MAX:
        return poll_question, poll_options, poll_explanation, None, description_text

    overflow_parts = [f"\U0001F4CB <b>Q{question_index + 1}/{total_questions}</b>", f"\n\n{full_body}"]
    if reply_text:
        overflow_parts.append(f"\n\n\U0001F4DD {reply_text}")
    if any_option_long:
        overflow_parts.append("\n\n\U0001F524 <b>Options:</b>")
        for i, opt in enumerate(options):
            overflow_parts.append(f"\n  <b>{chr(65 + i)})</b> {opt}")
    return poll_question, poll_options, poll_explanation, "".join(overflow_parts), None
