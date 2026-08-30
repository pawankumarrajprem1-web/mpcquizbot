"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..parsing import filter_words, parse_question_block, strip_source_noise

logger = logging.getLogger(__name__)


def _process_txt(content: str, remove_words: list[str], out_questions: list[dict]) -> int:
    """Parse a .txt upload using the same block-parsing engine as pasted
    text, plus the legacy `RT:`/`ID:`/`<ggn>...</ggn>` structured-field
    style for reply_text/file_id metadata."""
    ggn_blocks: list[str] = []

    def _replace_ggn(match) -> str:
        placeholder = f"GGN_PLACEHOLDER_{len(ggn_blocks)}"
        ggn_blocks.append(match.group(1))
        return f"RT: <ggn>{placeholder}</ggn>"

    import re

    protected = re.sub(r"<ggn>(.*?)</ggn>", _replace_ggn, content, flags=re.DOTALL)

    blocks = protected.strip().split("\n\n")
    processed = 0

    for block in blocks:
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        has_structured = any(ln.strip().startswith(("RT:", "ID:")) for ln in lines)

        reply_text: Optional[str] = None
        file_id: Optional[str] = None
        core_lines = lines

        if has_structured:
            reply_text, file_id, core_lines = None, None, []
            for ln in lines:
                stripped = ln.strip()
                if stripped.startswith("RT:"):
                    rt_content = stripped[3:].strip()
                    ph_match = re.search(r"<ggn>GGN_PLACEHOLDER_(\d+)</ggn>", rt_content)
                    if ph_match:
                        idx = int(ph_match.group(1))
                        reply_text = ggn_blocks[idx] if idx < len(ggn_blocks) else rt_content
                    else:
                        reply_text = rt_content
                    if remove_words:
                        reply_text = filter_words(reply_text, remove_words)
                    reply_text = strip_source_noise(reply_text)
                elif stripped.startswith("ID:"):
                    file_id = strip_source_noise(stripped[3:].strip())
                else:
                    core_lines.append(ln)

        parsed = parse_question_block("\n".join(core_lines))
        if not parsed or isinstance(parsed["correct_option_id"], list):
            continue

        q_text = parsed["question"]
        opts = parsed["options"]
        exp = parsed.get("explanation")
        if remove_words:
            q_text = filter_words(q_text, remove_words)
            opts = [filter_words(o, remove_words) for o in opts]
            if exp:
                exp = filter_words(exp, remove_words)
        q_text = strip_source_noise(q_text)
        opts = [strip_source_noise(o) for o in opts]
        if exp:
            exp = strip_source_noise(exp)

        if not q_text or len(opts) < 2:
            continue

        out_questions.append(
            {
                "question": q_text, "options": opts,
                "correct_option_id": parsed["correct_option_id"],
                "explanation": exp, "reply_text": reply_text, "file_id": file_id,
            }
        )
        processed += 1

    return processed


def _process_json(raw: dict, remove_words: list[str], out_questions: list[dict]) -> int:
    """Parse the simple JSON schema:
    `{"questions": [{"question_text", "options": [{"id","text"}],
    "correct_option_id", "explanation"?, "reference_text"?, "file_id"?}]}`
    """
    questions = raw.get("questions")
    if not isinstance(questions, list):
        raise ValueError("'questions' should be an array.")

    processed = 0
    for q in questions:
        try:
            if not isinstance(q, dict):
                continue
            if not all(k in q for k in ("question_text", "options", "correct_option_id")):
                continue
            question_text = q["question_text"]
            if remove_words:
                question_text = filter_words(question_text, remove_words)
            question_text = strip_source_noise(question_text)

            options_data = q["options"]
            if not isinstance(options_data, list) or len(options_data) < 2:
                continue

            options: list[str] = []
            id_to_index: dict = {}
            for opt in options_data:
                if not isinstance(opt, dict) or "id" not in opt or "text" not in opt:
                    continue
                text = opt["text"]
                if remove_words:
                    text = filter_words(text, remove_words)
                text = strip_source_noise(text)
                if not text:
                    continue
                id_to_index[opt["id"]] = len(options)
                options.append(text)
            if len(options) < 2:
                continue

            correct_id = q["correct_option_id"]
            if correct_id not in id_to_index:
                continue
            correct_index = id_to_index[correct_id]

            explanation = q.get("explanation")
            if explanation and remove_words:
                explanation = filter_words(explanation, remove_words)
            if explanation:
                explanation = strip_source_noise(explanation)

            reply_text = q.get("reference_text")
            if reply_text and remove_words:
                reply_text = filter_words(reply_text, remove_words)
            if reply_text:
                reply_text = strip_source_noise(reply_text)

            out_questions.append(
                {
                    "question": question_text, "options": options,
                    "correct_option_id": correct_index, "explanation": explanation,
                    "reply_text": reply_text, "file_id": q.get("file_id"),
                }
            )
            processed += 1
        except Exception:
            logger.debug("Skipped malformed question in JSON import", exc_info=True)
            continue
    return processed


def process_uploaded_file(
    content: bytes, filename: str, out_questions: list[dict], remove_words: list[str]
) -> tuple[Optional[int], Optional[str]]:
    """Parse an uploaded .txt or .json quiz-question file (bytes already in
    memory) and append parsed questions to `out_questions` in place.
    Returns (count_processed, error_message).
    """
    lower = filename.lower()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None, "❌ File is not valid UTF-8 text."

    try:
        if lower.endswith(".json"):
            data = json.loads(text)
            if not isinstance(data, dict) or "questions" not in data:
                return None, "❌ Invalid JSON format. Expected an object with a 'questions' array."
            count = _process_json(data, remove_words, out_questions)
        elif lower.endswith(".txt"):
            count = _process_txt(text, remove_words, out_questions)
        else:
            return None, "❌ Only .txt and .json files are supported."
        return count, None
    except json.JSONDecodeError as exc:
        return None, f"❌ Invalid JSON format: {exc}"
    except Exception as exc:
        logger.exception("process_uploaded_file failed for %s", filename)
        return None, f"⚠️ Error processing file: {exc}"
