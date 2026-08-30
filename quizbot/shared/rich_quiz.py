"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# A framework adapter: given a raw Bot API method name and its JSON params,
# perform the call and return the decoded JSON response (or raise).
SendRawFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

# A plain-text fallback sender: given text (already truncated/cleaned),
# send it as an ordinary message.
PlainSendFn = Callable[[str], Awaitable[Any]]

# ---------------------------------------------------------------------------
# Rich-text detection (ported verbatim from the original rich_quiz.py)
# ---------------------------------------------------------------------------

_HTML_TAG = re.compile(
    r"<(?:b|i|u|s|em|strong|code|pre|mark|h[1-6]|p|ul|ol|li|table|tr|td|th|"
    r"blockquote|details|summary|figure|figcaption|aside|sup|sub|hr|br|div|span|"
    r"tg-spoiler|tg-math|tg-math-block|tg-slideshow|tg-collage|tg-map|"
    r"img|video|audio)[\s/>]",
    re.IGNORECASE,
)

_MD_PATTERNS: list[re.Pattern] = [
    re.compile(r"^#{1,6}\s", re.MULTILINE),
    re.compile(r"\*\*\S[\s\S]*?\S\*\*|\*\*\S\*\*"),
    re.compile(r"(?<!\w)__(?!\s)\S[\s\S]*?\s[\s\S]*?(?<!\s)__(?!\w)"),
    re.compile(r"\*(?!\s)(?:[^*\n]|\\.)+?(?<!\s)\*"),
    re.compile(r"~~.+?~~"),
    re.compile(r"==.+?=="),
    re.compile(r"\|\|.+?\|\|"),
    re.compile(r"^\|.+\|.*\n\|[-:\s|]+\|", re.MULTILINE),
    re.compile(r"!\[.*?\]\([^)]+\)"),
    re.compile(r"\[.+?\]\([^)]+\)"),
    re.compile(r"\$\$[\s\S]+?\$\$"),
    re.compile(r"^```", re.MULTILINE),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"^>[ \t]", re.MULTILINE),
    re.compile(r"^---$", re.MULTILINE),
    re.compile(r"^\s*[-*]\s+\[[ xX]\]", re.MULTILINE),
    re.compile(r"\[\^.+?\]"),
]

_LATEX_PATTERNS: list[re.Pattern] = [
    re.compile(r"\$\$[\s\S]+?\$\$"),
    re.compile(r"(?<!\$)\$(?!\$)[^$\n]*[\\^_{}\[\]][^$\n]*(?<!\$)\$(?!\$)"),
    re.compile(r"\\\([\s\S]+?\\\)"),
    re.compile(r"\\\[[\s\S]+?\\\]"),
    re.compile(
        r"\\(?:frac|sqrt|sum|int|prod|lim|infty|alpha|beta|gamma|delta|"
        r"epsilon|theta|lambda|mu|pi|sigma|omega|Omega|nabla|partial|"
        r"cdot|times|div|pm|mp|leq|geq|neq|approx|equiv|propto|"
        r"vec|hat|bar|dot|ddot|overline|underline|mathbf|mathrm|mathit|"
        r"text|begin|end|matrix|pmatrix|bmatrix|cases|aligned)\b"
    ),
]

_OPTION_LETTERS = "ABCDEFGHIJ"
_PLACEHOLDER_Q = "Choose the correct option"


def _normalise_math_spacing(text: str) -> str:
    """Strip whitespace just inside ``$$...$$`` delimiters and ensure a
    space outside them where adjacent text touches, without adding
    newlines (Telegram's rich renderer handles layout itself)."""
    dd = re.compile(r"\$\$([\s\S]+?)\$\$")
    result: list[str] = []
    last_end = 0
    for m in dd.finditer(text):
        start, end = m.start(), m.end()
        content = m.group(1).strip()
        before = text[last_end:start]
        if last_end > 0 and before and not before[0].isspace():
            before = " " + before
        if before and not before[-1].isspace():
            before = before + " "
        result.append(before)
        result.append("$$")
        result.append(content)
        result.append("$$")
        last_end = end
    tail = text[last_end:]
    if result and tail and not tail[0].isspace():
        tail = " " + tail
    result.append(tail)
    return "".join(result)


def _is_rich(text: Optional[str]) -> bool:
    """Return True if *text* contains any rich-text or math markup."""
    if not text or not text.strip():
        return False
    if _HTML_TAG.search(text):
        return True
    for p in _LATEX_PATTERNS:
        if p.search(text):
            return True
    for p in _MD_PATTERNS:
        if p.search(text):
            return True
    return False


def _options_are_rich(options: list[str]) -> bool:
    return any(_is_rich(opt) for opt in options)


def _detect_mode(text: str) -> str:
    """Guess whether *text* is HTML or Markdown for sendRichMessage."""
    stripped = text.lstrip()
    if stripped.startswith("<") and _HTML_TAG.search(stripped[:200]):
        return "html"
    return "markdown"


def _make_letter_options(options: list[str]) -> list[str]:
    return [
        _OPTION_LETTERS[i] if i < len(_OPTION_LETTERS) else str(i + 1)
        for i in range(len(options))
    ]


# ---------------------------------------------------------------------------
# Generic sendRichMessage dispatch with graceful fallback
# ---------------------------------------------------------------------------


async def send_rich_or_fallback(
    send_raw: SendRawFn,
    plain_send: PlainSendFn,
    chat_id: int,
    text: str,
    *,
    thread_id: Optional[int] = None,
    plain_limit: int = 4096,
) -> bool:
    """Send *text* via ``sendRichMessage`` (auto-detecting markdown vs HTML),
    retrying with the other mode once, then falling back to a plain
    (truncated, tg-tag-stripped) message via *plain_send* if both attempts
    fail. Returns True if the rich send itself succeeded.

    This generalizes the original Creator Bot's `_send_rich_or_fallback`
    (leaderboards) and Runner Bot's `_send_rich_msg` (question/explanation
    pre-messages) into one shared implementation.
    """
    mode = _detect_mode(text)
    params: dict[str, Any] = {"chat_id": chat_id, "rich_message": {mode: text}}
    if thread_id:
        params["message_thread_id"] = thread_id
    try:
        await send_raw("sendRichMessage", params)
        return True
    except Exception as exc:
        logger.debug("sendRichMessage (%s) failed for chat=%s: %s -- retrying other mode", mode, chat_id, exc)

    other = "html" if mode == "markdown" else "markdown"
    params["rich_message"] = {other: text}
    try:
        await send_raw("sendRichMessage", params)
        return True
    except Exception as exc:
        logger.warning("sendRichMessage fallback also failed for chat=%s: %s", chat_id, exc)

    plain = re.sub(r"</?tg-[^>]+>", "", text)
    try:
        for i in range(0, len(plain), plain_limit):
            await plain_send(plain[i : i + plain_limit])
    except Exception as exc:
        logger.error("Plain-message fallback also failed for chat=%s: %s", chat_id, exc)
    return False


# ---------------------------------------------------------------------------
# Question-level dispatch (Runner Bot: pre-send rich content before a poll)
# ---------------------------------------------------------------------------


@dataclass
class RichDispatchResult:
    """Returned by `enrich_question_dispatch`. Fields left at their default
    mean "use the original value unchanged"."""

    poll_question_override: Optional[str] = None
    poll_options_override: Optional[list[str]] = None
    suppress_description: bool = False
    suppress_reply_text: bool = False
    case: int = 0  # 0=plain, 1/2/3/4 as documented below
    rich_sent: bool = False
    original_option_count: int = 0


async def enrich_question_dispatch(
    send_raw: SendRawFn,
    plain_send: PlainSendFn,
    chat_id: int,
    q: dict[str, Any],
    idx: int,
    total: int,
    *,
    thread_id: Optional[int] = None,
) -> RichDispatchResult:
    """Analyse a question dict (`question`, `options`, optional
    `reply_text`) and, if it contains rich markup, pre-send the appropriate
    content via ``sendRichMessage`` before the poll is sent.

    Four cases (see module docstring of the original for full rationale):
      1. Only the question is rich       -> send question (+ reference) rich;
                                             poll gets a placeholder question,
                                             real options.
      2. Only the options are rich       -> send question + enumerated rich
                                             options; poll gets placeholder
                                             question + letter options.
      3. Both question and options rich  -> combination of 1 + 2.
      4. Only reply_text is rich         -> send reply_text rich, separately;
                                             poll/question/options untouched.

    Returns a `RichDispatchResult` the caller applies as overrides on top of
    whatever `prepare_poll_data`-equivalent logic it already runs.
    """
    question_text: str = (q.get("question") or "").strip()
    options: list[str] = q.get("options", [])
    reply_text: str = (q.get("reply_text") or "").strip()

    q_is_rich = _is_rich(question_text)
    opts_are_rich = _options_are_rich(options)
    rt_is_rich = _is_rich(reply_text) if reply_text else False

    if not q_is_rich and not opts_are_rich and not rt_is_rich:
        return RichDispatchResult(case=0)

    res = RichDispatchResult(original_option_count=len(options))

    # Case 4 -- only reply_text is rich.
    if rt_is_rich and not q_is_rich and not opts_are_rich:
        ok = await send_rich_or_fallback(
            send_raw, plain_send, chat_id, _normalise_math_spacing(reply_text), thread_id=thread_id
        )
        res.case = 4
        res.rich_sent = ok
        res.suppress_reply_text = True
        return res

    prefix_line = f"**Q{idx + 1}/{total}**\n\n"

    # Case 1 or 3 -- question body is rich.
    if q_is_rich:
        body_parts: list[str] = [prefix_line, question_text]
        if opts_are_rich:
            body_parts.append("\n\n---\n\n**Options:**\n\n")
            for i, opt in enumerate(options):
                letter = _OPTION_LETTERS[i] if i < len(_OPTION_LETTERS) else str(i + 1)
                body_parts.append(f"**{letter})** {opt}\n\n")
        if reply_text:
            body_parts.append(f"\n\n---\n\n\U0001F4DD **Reference:**\n\n{reply_text}")

        rich_body = _normalise_math_spacing("".join(body_parts))
        ok = await send_rich_or_fallback(send_raw, plain_send, chat_id, rich_body, thread_id=thread_id)
        res.rich_sent = ok
        res.suppress_description = True
        res.suppress_reply_text = True
        res.poll_question_override = _PLACEHOLDER_Q

        if opts_are_rich:
            res.case = 3
            res.poll_options_override = _make_letter_options(options)
        else:
            res.case = 1
        return res

    # Case 2 -- only options are rich.
    if opts_are_rich:
        body_parts = [prefix_line, question_text]
        if reply_text:
            body_parts.append(f"\n\n---\n\n\U0001F4DD **Reference:**\n\n{reply_text}")
        body_parts.append("\n\n---\n\n**Options:**\n\n")
        for i, opt in enumerate(options):
            letter = _OPTION_LETTERS[i] if i < len(_OPTION_LETTERS) else str(i + 1)
            body_parts.append(f"**{letter})** {opt}\n\n")

        rich_body = _normalise_math_spacing("".join(body_parts))
        ok = await send_rich_or_fallback(send_raw, plain_send, chat_id, rich_body, thread_id=thread_id)
        res.case = 2
        res.rich_sent = ok
        res.suppress_description = True
        res.suppress_reply_text = True
        res.poll_question_override = _PLACEHOLDER_Q
        res.poll_options_override = _make_letter_options(options)
        return res

    return RichDispatchResult(case=0)
