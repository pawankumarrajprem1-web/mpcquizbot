"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

from quizbot.database import AIKeyRepository, get_db
from quizbot.shared import config
from quizbot.shared.utils.http import request_json

from .state import last_working_ai

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

AIQUIZ_DIFFICULTY = {
    "moderate": "Moderate — standard competitive exam level",
    "hard": "Hard — advanced level, tricky options",
    "extreme": "Extreme Hard — UPSC Mains/IAS depth, statement-based",
}
AIQUIZ_EXAM = {
    "ssc": "SSC CGL/CHSL pattern — factual, direct, speed-based",
    "civil": "UPSC Civil Services — analytical, multi-statement, multi-correct possible",
    "oneway": "Common One Day Exam — mixed MCQ, standard pattern",
}
AIQUIZ_LANG = {
    "en": "English",
    "hi": "Hindi (Devanagari script)",
    "hinglish": "Hinglish (Hindi words in English script)",
    "bn": "Bengali (বাংলা script)",
    "te": "Telugu (తెలుగు script)",
    "mr": "Marathi (मराठी script)",
    "ta": "Tamil (தமிழ் script)",
    "gu": "Gujarati (ગુજરાતી script)",
    "kn": "Kannada (ಕನ್ನಡ script)",
    "pa": "Punjabi (ਪੰਜਾਬੀ script)",
    "ur": "Urdu (اردو script)",
    "or": "Odia/Oriya (ଓଡ଼ିଆ script)",
}
AIQUIZ_LANG_UI = {
    "en": "🇬🇧 English",
    "hi": "🇮🇳 Hindi",
    "hinglish": "🔀 Hinglish",
    "bn": "🟠 Bengali",
    "te": "🟣 Telugu",
    "mr": "🟤 Marathi",
    "ta": "🟡 Tamil",
    "gu": "🟢 Gujarati",
    "kn": "🔵 Kannada",
    "pa": "🟠 Punjabi",
    "ur": "🌙 Urdu",
    "or": "🔶 Odia",
}

QUESTION_FORMAT = """[TASK]Generate {count} MCQ on: "{topic}"
[STYLE]{diff}|{exam}
[LANG]{lang}
[RULES]JSON array only. No prose. No markdown. Start with [ end with ]
Each item: {{"q":"<270ch","o":["A","B","C","D"],"c":[0],"e":"<150ch or null"}}
c = 0-based correct index array. Multi-correct allowed.
[OUTPUT]"""

QUESTION_FORMAT_BILINGUAL = """[TASK]Generate {count} MCQ on: "{topic}"
[STYLE]{diff}|{exam}
[LANG]Bilingual: {lang1} / {lang2}
[RULES]JSON array only. No prose. No markdown. Start with [ end with ]
Each item: {{"q":"<question in {lang1_short}> / <question in {lang2_short}>","o":["<A in {lang1_short}> / <A in {lang2_short}>","<B in {lang1_short}> / <B in {lang2_short}>","<C in {lang1_short}> / <C in {lang2_short}>","<D in {lang1_short}> / <D in {lang2_short}>"],"c":[0],"e":"<exp in {lang1_short}> / <exp in {lang2_short}> or null"}}
Use / as separator between the two languages in every text field.
Keep total q length ≤270 chars, each option ≤90 chars.
[OUTPUT]"""


async def get_provider_keys(user_id: int, provider: str) -> list[dict]:
    """All stored keys for a provider, ordered for round-robin (fewest
    failures / oldest first, per the repository's ORDER BY)."""
    repo = AIKeyRepository(get_db())
    return await repo.list_for_provider(user_id, provider)


async def get_provider_key_single(user_id: int, provider: str) -> Optional[str]:
    keys = await get_provider_keys(user_id, provider)
    return keys[0]["api_key"] if keys else None


async def _mark_key(key_id: int, failed: bool) -> None:
    repo = AIKeyRepository(get_db())
    await repo.mark(key_id, failed)


async def _call_gemini(api_key: str, prompt: str, max_tokens: int = 4096) -> str:
    payload = {
        "system_instruction": {
            "parts": [{
                "text": "You are an expert quiz question generator. Output ONLY the formatted "
                        "questions, nothing else — no intro, no numbering outside the format, no extra text."
            }]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
    }
    status, data = await request_json(
        "POST", config.GEMINI_URL, json_body=payload,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
    )
    if status != 200:
        raise RuntimeError(f"Gemini {status}: {str(data)[:300]}")
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


async def _call_groq(api_key: str, prompt: str, max_tokens: int = 4096) -> str:
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "You are an expert quiz question generator. Output only the formatted questions."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    status, data = await request_json(
        "POST", config.GROQ_URL, json_body=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    if status != 200:
        raise RuntimeError(f"Groq {status}: {str(data)[:300]}")
    return data["choices"][0]["message"]["content"].strip()


async def _call_openrouter(api_key: str, prompt: str, max_tokens: int = 4096) -> str:
    payload = {
        "model": "openrouter/free",
        "messages": [
            {"role": "system", "content": "Output ONLY a valid JSON array. No prose, no markdown, no explanation."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    status, data = await request_json(
        "POST", OPENROUTER_CHAT_URL, json_body=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/",
            "X-Title": "Quiz Bot",
        },
    )
    if status == 200:
        content = data["choices"][0]["message"]["content"].strip()
        if content and content.startswith("["):
            return content
        raise RuntimeError(f"Non-JSON response from openrouter/free: {content[:200]}")
    if status in (429, 503, 529):
        raise RuntimeError(f"OpenRouter free router rate-limited ({status}): {str(data)[:300]}")
    raise RuntimeError(f"OpenRouter {status}: {str(data)[:300]}")


async def _call_pollinations(prompt: str, max_tokens: int = 4096) -> str:
    payload = {
        "model": "openai",
        "messages": [
            {"role": "system", "content": "You are an expert quiz question generator. Output ONLY the formatted questions, nothing else."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
        "stream": False,
    }
    status, data = await request_json("POST", config.POLLINATIONS_URL, json_body=payload)
    if status != 200:
        raise RuntimeError(f"Pollinations {status}: {str(data)[:300]}")
    return data["choices"][0]["message"]["content"].strip()


async def _try_call(provider: str, api_key: str, prompt: str, max_tokens: int) -> str:
    if provider == "gemini":
        return await _call_gemini(api_key, prompt, max_tokens)
    if provider == "groq":
        return await _call_groq(api_key, prompt, max_tokens)
    if provider == "openrouter":
        return await _call_openrouter(api_key, prompt, max_tokens)
    raise ValueError(f"Unknown provider {provider}")


async def ai_generate(user_id: int, prompt: str, max_tokens: int = 4096) -> str:
    """Round-robin through the user's keys per provider, then the shared
    default OpenRouter keys, then Pollinations as a final free fallback.

    Priority: Gemini -> Groq -> OpenRouter (user key) -> OpenRouter
    (default keys) -> Pollinations.
    """
    cached = last_working_ai.get(user_id)
    if cached:
        try:
            result = await _try_call(cached["provider"], cached["api_key"], prompt, max_tokens)
            if cached.get("key_id"):
                await _mark_key(cached["key_id"], failed=False)
            return result
        except Exception:
            if cached.get("key_id"):
                await _mark_key(cached["key_id"], failed=True)
            last_working_ai.pop(user_id, None)

    for provider in ("gemini", "groq", "openrouter"):
        keys = await get_provider_keys(user_id, provider)
        for k in keys:
            try:
                result = await _try_call(provider, k["api_key"], prompt, max_tokens)
                await _mark_key(k["id"], failed=False)
                last_working_ai[user_id] = {"provider": provider, "key_id": k["id"], "api_key": k["api_key"]}
                return result
            except Exception:
                await _mark_key(k["id"], failed=True)

    for def_key in config.OPENROUTER_DEFAULT_KEYS:
        try:
            result = await _call_openrouter(def_key, prompt, max_tokens)
            last_working_ai[user_id] = {"provider": "openrouter", "key_id": None, "api_key": def_key}
            return result
        except Exception:
            continue

    result = await _call_pollinations(prompt, max_tokens)
    last_working_ai[user_id] = {"provider": "pollinations", "key_id": None, "api_key": ""}
    return result


def parse_ai_questions(raw: str) -> list[dict]:
    """Parse the JSON array an AI provider returned into question dicts.
    Tolerates extra text before/after the JSON and malformed items; falls
    back to a legacy `✅`-marked text format if no valid JSON is found.
    """
    questions: list[dict] = []

    clean = re.sub(r"```(?:json)?\s*", "", raw).strip()
    json_match = re.search(r"\[.*\]", clean, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            if isinstance(data, list):
                for obj in data:
                    if not isinstance(obj, dict):
                        continue
                    q = str(obj.get("q", "")).strip()[:280]
                    o = obj.get("o", [])
                    c = obj.get("c", [])
                    e = obj.get("e") or None
                    if not q or not isinstance(o, list) or len(o) < 2:
                        continue
                    if not isinstance(c, list) or not c:
                        continue
                    opts = [str(x).strip()[:95] for x in o if str(x).strip()]
                    if len(opts) < 2:
                        continue
                    valid_c = [int(i) for i in c if isinstance(i, (int, float)) and 0 <= int(i) < len(opts)]
                    if not valid_c:
                        continue
                    coid = valid_c[0] if len(valid_c) == 1 else valid_c
                    if e:
                        e = str(e).strip()[:200]
                    questions.append({
                        "question": q, "options": opts,
                        "correct_option_id": coid, "explanation": e,
                        "file_id": None, "reply_text": None,
                    })
                if questions:
                    return questions
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Legacy fallback parser: "✅"-marked plain-text blocks.
    blocks = re.split(r"\n{2,}", raw.strip())
    for blk in blocks:
        blk = blk.strip()
        if not blk:
            continue
        lines = [ln.strip() for ln in blk.split("\n") if ln.strip()]
        if len(lines) < 3:
            continue
        question = lines[0]
        options, correct_ids, explanation = [], [], None
        for ln in lines[1:]:
            if ln.startswith("Ex:"):
                explanation = ln[3:].strip()[:200]
                continue
            is_correct = "✅" in ln
            opt = re.sub(r"^[A-Da-d][.)]\ *", "", ln.replace("✅", "").strip())
            if is_correct:
                correct_ids.append(len(options))
            if opt:
                options.append(opt)
        if not question or len(options) < 2 or not correct_ids:
            continue
        coid = correct_ids[0] if len(correct_ids) == 1 else correct_ids
        questions.append({
            "question": question, "options": options,
            "correct_option_id": coid, "explanation": explanation,
            "file_id": None, "reply_text": None,
        })
    return questions


async def generate_in_chunks(
    user_id: int, topic: str, total: int, lang: str, diff: str, exam: str,
    status_msg: Any, chunk_size: int = 25, bilingual_lang2: Optional[str] = None,
) -> list[dict]:
    """Generate `total` questions in chunks (large enough for efficiency,
    small enough to avoid truncation), retrying short chunks once with an
    explicit count reminder, updating `status_msg` after each chunk."""
    all_q: list[dict] = []
    consecutive_failures = 0
    chunk_num = 0

    lang1_name = AIQUIZ_LANG.get(lang, "English")
    lang2_name = AIQUIZ_LANG.get(bilingual_lang2, "") if bilingual_lang2 else ""

    def _short(name: str) -> str:
        return name.split(" (")[0].split(" —")[0].strip()

    while len(all_q) < total:
        needed = total - len(all_q)
        chunk = min(chunk_size, needed)
        chunk_num += 1

        try:
            await status_msg.edit_text(
                f"🤖 <b>Generating...</b> ({len(all_q)}/{total} ready)\n"
                f"📌 {topic} | Batch {chunk_num} — fetching {chunk} questions"
                + (f" | 🌐 {_short(lang1_name)}/{_short(lang2_name)}" if bilingual_lang2 else ""),
                parse_mode="HTML",
            )
        except Exception:
            pass

        if bilingual_lang2:
            prompt = QUESTION_FORMAT_BILINGUAL.format(
                count=chunk, topic=topic,
                diff=AIQUIZ_DIFFICULTY.get(diff, "Moderate"),
                exam=AIQUIZ_EXAM.get(exam, "Common One Day Exam"),
                lang1=lang1_name, lang2=lang2_name,
                lang1_short=_short(lang1_name), lang2_short=_short(lang2_name),
            )
        else:
            prompt = QUESTION_FORMAT.format(
                count=chunk, topic=topic, lang=lang1_name,
                diff=AIQUIZ_DIFFICULTY.get(diff, "Moderate"),
                exam=AIQUIZ_EXAM.get(exam, "Common One Day Exam"),
            )

        tok_per_q = 350 if bilingual_lang2 else 220
        max_tok = max(2048, chunk * tok_per_q)

        try:
            raw = await ai_generate(user_id, prompt, max_tokens=max_tok)
            parsed = parse_ai_questions(raw)

            if len(parsed) < chunk:
                retry_prompt = (
                    f"IMPORTANT: You must return EXACTLY {chunk} items in the JSON array. "
                    f"You previously returned {len(parsed)}. Generate the full {chunk} now.\n\n" + prompt
                )
                raw2 = await ai_generate(user_id, retry_prompt, max_tokens=max_tok)
                parsed2 = parse_ai_questions(raw2)
                if len(parsed2) > len(parsed):
                    parsed = parsed2

            if parsed:
                all_q.extend(parsed[:chunk])
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logger.error("Chunk %d empty after retry (%d/3)", chunk_num, consecutive_failures)
                if consecutive_failures >= 3:
                    logger.error("3 consecutive empty chunks — stopping early")
                    break
        except Exception as e:
            consecutive_failures += 1
            logger.error("Chunk %d exception: %s", chunk_num, e)
            if consecutive_failures >= 3:
                break

        await asyncio.sleep(0.3)

    return all_q[:total]


async def gemini_page_questions(
    api_key: str, page_pdf_b64: str, page_num: int, questions_hint: int, diff: str, exam: str, lang: str,
) -> list[dict]:
    """Send a single PDF page (as base64-encoded inline PDF bytes) to
    Gemini's vision-capable model and parse the returned questions."""
    prompt = (
        f"You are an expert exam question generator.\n"
        f"This is page {page_num} of a study PDF.\n"
        f"Language: {AIQUIZ_LANG.get(lang, 'English')}\n"
        f"Difficulty: {AIQUIZ_DIFFICULTY.get(diff, 'Moderate')}\n"
        f"Exam style: {AIQUIZ_EXAM.get(exam, 'Common One Day Exam')}\n\n"
        f"Generate up to {questions_hint} high-quality MCQ questions "
        f"strictly based on content visible in this page. "
        f"If the page has very little content, generate fewer questions — quality over quantity.\n\n"
        f"YOU MUST RESPOND WITH ONLY A JSON ARRAY. No text before or after. No markdown.\n"
        f'Each object: {{"q":"question","o":["A","B","C","D"],"c":[0],"e":"explanation"}}\n'
        f"- q: question text (max 270 chars)\n"
        f"- o: 2-4 options (max 90 chars each)\n"
        f"- c: correct indices array (0-based)\n"
        f"- e: short explanation (max 150 chars, or null)\n"
        f"Start your response with [ and end with ]"
    )
    payload = {
        "system_instruction": {
            "parts": [{"text": "You are an expert exam question generator. Output ONLY valid JSON arrays. No prose, no markdown."}]
        },
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": "application/pdf", "data": page_pdf_b64}},
                {"text": prompt},
            ],
        }],
        "generationConfig": {"maxOutputTokens": max(512, questions_hint * 220), "temperature": 0.5},
    }
    status, data = await request_json(
        "POST", config.GEMINI_URL, json_body=payload,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
    )
    if status != 200:
        raise RuntimeError(f"Gemini {status}: {str(data)[:200]}")
    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    return parse_ai_questions(raw)
