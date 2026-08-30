"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import re
import unicodedata as _ud
from typing import Optional

_LATEX_MAP_NOT_USED = None  # (LaTeX/markdown cleanup lives in shared.utils.text)


def _is_emoji(char: str) -> bool:
    """Return True if `char` is a single emoji (excluding the ✅ marker)."""
    if char == "✅":
        return False
    cp = ord(char)
    if 0x1F300 <= cp <= 0x1FAFF:
        return True
    if 0x2600 <= cp <= 0x26FF:
        return True
    if 0x2700 <= cp <= 0x27BF:
        return True
    if 0xFE00 <= cp <= 0xFE0F:
        return True
    if 0x1F1E0 <= cp <= 0x1F1FF:
        return True
    if 0x231A <= cp <= 0x231B:
        return True
    if 0x23E9 <= cp <= 0x23F3:
        return True
    if 0x25AA <= cp <= 0x25FE:
        return True
    if 0x2614 <= cp <= 0x2615:
        return True
    if 0x2648 <= cp <= 0x2653:
        return True
    return False


def _line_is_emoji_separator(line: str) -> bool:
    """True if the line consists only of emoji/emoji-modifier characters."""
    s = line.strip()
    if not s:
        return False
    for ch in s:
        if ch in ("️", "‍", "︎"):
            continue
        if not _is_emoji(ch):
            return False
    return True


def clean_markdown(text: str) -> str:
    """Strip common markdown emphasis/headings from pasted question text."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    return text


_TABLE_LINE_RE = re.compile(r"^\|.*\|$")


def _pad_table_blocks(text: str) -> str:
    """Ensure blank lines surround any markdown-table block so tables
    render distinctly from surrounding prose."""
    if "|" not in text:
        return text
    lines = text.split("\n")
    segments: list[tuple[str, bool]] = []
    i, n = 0, len(lines)
    while i < n:
        if _TABLE_LINE_RE.match(lines[i].strip()):
            block = []
            while i < n and _TABLE_LINE_RE.match(lines[i].strip()):
                block.append(lines[i])
                i += 1
            segments.append(("\n".join(block), True))
        else:
            segments.append((lines[i], False))
            i += 1
    if not segments:
        return text
    out = segments[0][0]
    for k in range(1, len(segments)):
        prev_is_table = segments[k - 1][1]
        cur_is_table = segments[k][1]
        sep = "\n\n" if (prev_is_table or cur_is_table) else "\n"
        out += sep + segments[k][0]
    if segments[-1][1]:
        out += "\n\n"
    return out


_ABCD_RE = re.compile(r"^[A-Da-d]\)")


def parse_question_block(blk: str) -> Optional[dict]:
    """Parse one question block (separated by a blank line in a larger
    paste) into {question, options, correct_option_id, explanation}.

    `correct_option_id` is an int (single ✅) or a list[int] (multiple ✅).
    Returns None if the block doesn't parse into a valid question.

    Newlines inside the question text (e.g. a passage followed by a blank
    line, followed by the actual question) are preserved exactly -- only
    the separator/option/marker lines used to structurally locate the
    options are stripped away, never the blank lines a user typed on
    purpose for spacing within the question itself.
    """
    blk = clean_markdown(blk)
    # Keep blank lines here (structure-preserving) -- they're only used
    # for splitting on the caller side (blocks separated by "\n\n"); a
    # blank line *inside* one block is an intentional paragraph break in
    # the question and must survive into the final `question` string.
    all_lines = blk.split("\n")
    if not any(ln.strip() for ln in all_lines):
        return None

    exp = None
    filtered = []
    for ln in all_lines:
        if ln.strip().startswith("Ex:"):
            exp = ln.strip()[3:].strip()
        else:
            filtered.append(ln)
    all_lines = filtered

    # Structural scan (separator / A-D markers) only ever needs to look at
    # non-blank lines, but indexes must map back into `all_lines` so the
    # split point doesn't chop a preserved blank line in half.
    non_blank_idx = [i for i, ln in enumerate(all_lines) if ln.strip()]
    if not non_blank_idx:
        return None

    sep_line_idx = None
    for i in non_blank_idx:
        if _line_is_emoji_separator(all_lines[i]):
            sep_line_idx = i
            break

    abcd_line_idx = None
    for i in non_blank_idx:
        if _ABCD_RE.match(all_lines[i].strip()):
            abcd_line_idx = i
            break

    first_nonblank = non_blank_idx[0]
    if sep_line_idx is not None:
        q_lines = all_lines[:sep_line_idx]
        opt_lines = all_lines[sep_line_idx + 1:]
    elif abcd_line_idx is not None and abcd_line_idx > first_nonblank:
        q_lines = all_lines[:abcd_line_idx]
        opt_lines = all_lines[abcd_line_idx:]
    else:
        # No structural marker found -- fall back to "first non-blank line
        # is the question, everything after is options" (matches the
        # original single-line-question behaviour).
        q_lines = all_lines[: first_nonblank + 1]
        opt_lines = all_lines[first_nonblank + 1:]

    # Trim only leading/trailing wholly-blank lines from the question (so
    # e.g. a stray blank line right before the separator doesn't leave a
    # trailing "\n"), but keep every blank line that falls *between* two
    # real content lines -- that's the intentional paragraph break.
    while q_lines and not q_lines[0].strip():
        q_lines = q_lines[1:]
    while q_lines and not q_lines[-1].strip():
        q_lines = q_lines[:-1]
    question = _pad_table_blocks("\n".join(q_lines))

    opts: list[str] = []
    coids: list[int] = []
    for ln in opt_lines:
        if not ln.strip():
            continue
        ln = ln.strip()
        ln = re.sub(r"^[A-Da-d]\)\s*", "", ln)
        if "✅" in ln:
            coids.append(len(opts))
            ln = ln.replace("✅", "").strip()
        opts.append(ln)

    if not question or len(opts) < 2 or not coids:
        return None

    coid = coids[0] if len(coids) == 1 else coids
    return {
        "question": question,
        "options": opts,
        "correct_option_id": coid,
        "explanation": exp,
    }


def filter_words(text: Optional[str], remove_words: list[str]) -> Optional[str]:
    """Strip `[n/m]` progress markers and any user-configured remove-words
    from `text`, while preserving newlines exactly as typed/pasted.

    Only horizontal whitespace (spaces/tabs) is collapsed -- line breaks
    are never touched, so multi-line questions/options/explanations keep
    their original line structure end-to-end.
    """
    if not text:
        return text
    text = re.sub(r"\[\s*\d+\s*/\s*\d+\s*\]", "", text)
    if remove_words:
        for w in remove_words:
            text = re.sub(rf"\b{re.escape(w)}\b", "", text, flags=re.IGNORECASE)
    # Collapse runs of spaces/tabs only (never \n) and trim horizontal
    # whitespace at the start/end of each line, without merging lines.
    lines = [re.sub(r"[ \t]+", " ", ln).strip(" \t") for ln in text.split("\n")]
    return "\n".join(lines).strip("\n")


def strip_source_noise(text: Optional[str]) -> Optional[str]:
    """Remove leaked `[Q 3/10]`-style progress markers, raw URLs, t.me
    links, and @mentions that sometimes end up pasted into quiz text.

    The bracket/paren marker only matches when it actually looks like a
    progress tag -- either a `Q` prefix (`[Q3]`, `(Q.5)`) or a `n/m` pair
    (`[11/100]`, `(3/10)`). A bare lone number in brackets/parens, like
    `(1)` or `[2]`, is legitimate question content (e.g. an enumerated
    list: "(1) Anaphase (2) Metaphase") and must never be stripped.
    """
    if not text:
        return text
    pattern = (
        r"(?:[\[\(]\s*Q\.?\s*\d+(?:\s*/\s*\d+)?\s*[\]\)]|"
        r"[\[\(]\s*\d+\s*/\s*\d+\s*[\]\)]|"
        r"\bQ\.?\s*\d+\s*/\s*\d+\)?|https?://[^\s]+|t\.me/[^\s]+|@\w+)"
    )
    return re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
