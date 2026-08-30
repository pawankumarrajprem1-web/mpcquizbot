"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import asyncio
import logging
import time
from io import BytesIO

from pyrogram import Client, filters
from pyrogram.types import Message

from quizbot.database import QuizRepository, get_db
from quizbot.shared import config
from quizbot.shared.html.quiz_report import render_quiz_html
from quizbot.shared.utils import is_premium_user
from quizbot.shared.utils.http import get_session, request_json

from ..ratelimit import ratelimit

logger = logging.getLogger(__name__)

# Only one test-series PDF job runs at a time, to avoid overloading the
# external PDF microservice with concurrent large-document renders.
_TSR_LOCK = asyncio.Lock()


@ratelimit("default")
async def whtml_cmd(c: Client, m: Message) -> None:
    """/whtml <quiz_id> -- generate and send an interactive, self-contained
    HTML exam-style report for one of the caller's own quizzes."""
    parts = m.text.split()
    if len(parts) < 2:
        await m.reply("Usage: `/whtml QUIZID`")
        return
    qid = parts[1].strip()

    status = await m.reply("Fetching quiz data...")
    quiz = await QuizRepository(get_db()).get(qid)
    if not quiz:
        await status.edit_text("Quiz not found.")
        return
    if quiz.get("creator_id") != m.from_user.id:
        await status.edit_text("This is not your quiz.")
        return

    try:
        html_bytes, filename = await render_quiz_html(quiz, mode="exam")
    except Exception as exc:
        logger.exception("render_quiz_html failed for qid=%s", qid)
        await status.edit_text(f"Error generating report: {exc}")
        return

    await status.edit_text("Uploading report...")
    buf = BytesIO(html_bytes)
    buf.name = filename
    try:
        await m.reply_document(
            document=buf,
            file_name=filename,
            caption=(
                f"**Quiz Report: {quiz.get('quiz_name', qid)}**\n"
                f"{len(quiz.get('questions', []))} questions"
            ),
        )
        await status.delete()
    except Exception as exc:
        logger.exception("Failed to send whtml report for qid=%s", qid)
        await status.edit_text(f"Failed to send file: {exc}")


def _parse_testseries_args(raw: str) -> tuple[str, str, list[str]]:
    """Parse `/testseries QID1 QID2 mode=inline title=My_Title` into
    (mode, title, quiz_ids)."""
    tokens = raw.split()
    mode = "keyonly"
    title_override = None
    quiz_ids: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low.startswith("mode="):
            val = low.split("=", 1)[1]
            if val in ("inline", "keyonly"):
                mode = val
        elif low.startswith("title="):
            title_override = tok.split("=", 1)[1].replace("_", " ")
        else:
            quiz_ids.append(tok.strip())
    title = title_override or "Mock Test"
    return mode, title, quiz_ids


async def _generate_pdf_via_api(quizzes: list[dict], mode: str, title: str, poll_timeout: int = 180) -> bytes:
    """Delegate PDF rendering to the external microservice at
    `config.PDF_API_BASE`. Raises RuntimeError on any failure."""
    questions_payload = []
    for quiz in quizzes:
        for q in quiz.get("questions", []):
            options = [str(o) for o in q.get("options", []) if o]
            if not options:
                continue
            questions_payload.append(
                {
                    "question": str(q.get("question", "")).strip(),
                    "options": options,
                    "correct_option_id": q.get("correct_option_id", q.get("correct_option", 0)),
                    "explanation": str(q.get("explanation") or "").strip(),
                }
            )
    if not questions_payload:
        raise RuntimeError("No usable questions (with options) found in the given quiz(es).")

    payload = {
        "questions_json": questions_payload,
        "institute_name": "Quiz Creator",
        "tagline": "Test Series",
        "exam_title": title,
        "solution_display": "inline" if mode == "inline" else "end",
        "quiz_names": [str(q.get("quiz_name") or q.get("qid") or "") for q in quizzes],
        "async": True,
    }

    base = config.PDF_API_BASE.rstrip("/")
    status, job = await request_json("POST", f"{base}/api/generate", json_body=payload)
    if status != 200 or not isinstance(job, dict):
        raise RuntimeError(f"PDF API rejected the request (HTTP {status}): {job}")
    if job.get("error"):
        raise RuntimeError(f"PDF API error: {job['error']}")

    progress_url = base + job["progress_url"]
    download_url = base + job["download_url"]

    deadline = time.time() + poll_timeout
    while time.time() < deadline:
        pstatus, pjob = await request_json("GET", progress_url)
        if not isinstance(pjob, dict):
            raise RuntimeError("PDF API returned an unexpected progress response.")
        job_status = pjob.get("status")
        if job_status == "error":
            raise RuntimeError(f"PDF generation failed: {pjob.get('error', 'unknown error')}")
        if job_status == "done":
            break
        await asyncio.sleep(1.2)
    else:
        raise RuntimeError("PDF generation timed out -- try fewer quizzes.")

    # request_json only returns parsed JSON/text, so the binary PDF body is
    # fetched directly via the shared session instead.
    session = await get_session()
    async with session.get(download_url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"PDF download failed (HTTP {resp.status}).")
        return await resp.read()


@ratelimit("default")
async def testseries_cmd(c: Client, m: Message) -> None:
    """/testseries (or /tsr, /mocktest) QID1 [QID2 ...] [mode=inline|keyonly]
    [title=Your_Title] -- generate a book-style PDF test series from one or
    more of the caller's own quizzes, via the external PDF microservice."""
    uid = m.from_user.id

    if not config.PDF_API_BASE:
        await m.reply(
            "PDF generation is not configured on this bot (no PDF_API_BASE set). "
            "Ask the bot operator to configure a PDF microservice, or use /whtml "
            "for an interactive HTML report instead."
        )
        return

    if _TSR_LOCK.locked():
        await m.reply(
            "**System busy** -- another test series PDF is being generated. "
            "Only one generation runs at a time. Please try again shortly."
        )
        return

    if not await is_premium_user(uid):
        await m.reply("**Premium feature** -- the PDF generator is for premium users only. Use /pay.")
        return

    raw = m.text.split(maxsplit=1)[1].strip() if len(m.text.split(maxsplit=1)) > 1 else ""
    if not raw:
        await m.reply(
            "**Mock Test PDF Generator**\n\n"
            "Usage: `/testseries QID1 [QID2 QID3...] [mode=inline|keyonly] [title=Your_Title]`\n\n"
            "`mode=inline` -- answer & explanation after every question\n"
            "`mode=keyonly` -- questions only, answer key at the end (default)\n\n"
            "Example: `/testseries GGN123 GGN456 mode=keyonly title=SSC_Mock_2026`"
        )
        return

    mode, title, quiz_ids = _parse_testseries_args(raw)
    if not quiz_ids:
        await m.reply("No quiz IDs found. Usage: `/testseries GGN123 GGN456`")
        return

    async with _TSR_LOCK:
        status = await m.reply(f"Fetching {len(quiz_ids)} quiz(es)...")
        quiz_repo = QuizRepository(get_db())

        quizzes, failed, not_owner = [], [], []
        for qid in quiz_ids:
            quiz = await quiz_repo.get(qid)
            if not quiz or not quiz.get("questions"):
                failed.append(qid)
                continue
            if quiz.get("creator_id") != uid:
                not_owner.append(qid)
                continue
            quizzes.append(quiz)

        if (failed or not_owner) and quizzes:
            notes = []
            if failed:
                notes.append(f"Not found/empty: `{', '.join(failed)}`")
            if not_owner:
                notes.append(f"Not created by you: `{', '.join(not_owner)}`")
            await status.edit_text(
                "Some quizzes were skipped:\n" + "\n".join(notes) +
                f"\n\nProceeding with {len(quizzes)} valid quiz(es)..."
            )
            await asyncio.sleep(2)

        if not quizzes:
            if not_owner:
                await status.edit_text(f"You are not the creator of the requested quiz(es): `{', '.join(not_owner)}`")
            else:
                await status.edit_text("No valid quizzes found.")
            return

        total_q = sum(len(q.get("questions", [])) for q in quizzes)
        await status.edit_text(
            f"Generating PDF...\n\nQuizzes: **{len(quizzes)}**\nQuestions: **{total_q}**\nTitle: **{title}**"
        )

        try:
            pdf_bytes = await _generate_pdf_via_api(quizzes, mode, title)
        except Exception as exc:
            logger.exception("testseries PDF generation failed")
            await status.edit_text(f"PDF generation failed: {exc}")
            return

        await status.edit_text("Uploading PDF...")
        ids_str = "_".join(quiz_ids[:3]) + ("_etc" if len(quiz_ids) > 3 else "")
        filename = f"MockTest_{ids_str}.pdf"
        buf = BytesIO(pdf_bytes)
        buf.name = filename
        caption = f"**{title}**\n\nTests: {len(quizzes)} | Questions: {total_q}"
        try:
            await m.reply_document(document=buf, file_name=filename, caption=caption)
            await status.delete()
        except Exception as exc:
            logger.exception("Failed to send testseries PDF")
            await status.edit_text(f"Failed to send file: {exc}")


def register(app: Client) -> None:
    app.on_message(filters.command("whtml") & filters.private)(whtml_cmd)
    app.on_message(filters.command(["testseries", "tsr", "mocktest"]) & filters.private)(testseries_cmd)
