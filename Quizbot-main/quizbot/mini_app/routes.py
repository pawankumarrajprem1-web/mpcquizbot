"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from quizbot.database import QuizRepository, UserRepository, get_db
from quizbot.shared import config

from . import player_service
from .access import check_play_access, check_premium_gate
from .crypto import derive_session_key, encrypt_json
from .telegram_auth import verify_init_data

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_STATIC_DIR = Path(__file__).parent / "static"


class StartSessionBody(BaseModel):
    qid: str
    mode: str  # "practice" | "exam"
    # Optional per-attempt overrides chosen by the player on the mini app's
    # start-options screen. None/omitted means "use the quiz's saved
    # setting" for that field. These NEVER touch the saved quiz config in
    # the database -- they only shape this one attempt's in-memory session
    # (see player_service.start_session), so a creator's own configured
    # "exam" settings for leaderboard purposes stay intact unless the
    # player themselves opted to override them for their own attempt.
    timer: Optional[int] = None
    negative_marks: Optional[float] = None
    shuffle_questions: Optional[bool] = None
    shuffle_options: Optional[bool] = None


class AnswerBody(BaseModel):
    attempt_id: str
    position: int
    selected: list[int]


class CompleteBody(BaseModel):
    attempt_id: str


def _clamp_optional_int(value: Optional[int], lo: int, hi: int) -> Optional[int]:
    if value is None:
        return None
    return max(lo, min(hi, int(value)))


def _clamp_optional_float(value: Optional[float], lo: float, hi: float) -> Optional[float]:
    if value is None:
        return None
    return max(lo, min(hi, float(value)))


def _require_bot_token() -> str:
    # Whichever bot's token the Mini App is registered under -- both bots
    # can point their WebApp buttons at the same Mini App, and initData is
    # always signed with the token of the bot that opened it, so either
    # CREATOR_BOT_TOKEN or RUNNER_BOT_TOKEN verifies correctly as long as
    # both are set. We try both and accept the first that verifies.
    return config.CREATOR_BOT_TOKEN or config.RUNNER_BOT_TOKEN or ""


async def _authenticate(x_telegram_init_data: Optional[str]) -> tuple[int, str]:
    """Verify initData against whichever configured bot token matches.
    Returns (user_id, display_name) or raises 401. No detail is echoed back
    on failure."""
    if not x_telegram_init_data:
        raise HTTPException(status_code=401)

    for token in (config.CREATOR_BOT_TOKEN, config.RUNNER_BOT_TOKEN):
        if not token:
            continue
        session = verify_init_data(x_telegram_init_data, token)
        if session:
            user = session.user
            name = user.first_name or user.username or str(user.id)
            if user.last_name:
                name = f"{name} {user.last_name}"
            return user.id, name

    raise HTTPException(status_code=401)


@router.get("/quiz-info")
async def quiz_info(
    qid: str,
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
) -> dict:
    """Lightweight, read-only lookup of a quiz's name/question count/default
    timer & negative marking -- used to populate the start/options screen
    BEFORE the player has chosen final settings and BEFORE a real attempt is
    created. Deliberately does not call player_service.start_session (that
    creates a quiz_attempts row); calling this endpoint any number of times
    never creates attempts or touches the database beyond a read, so
    re-opening the mini app repeatedly doesn't pollute a player's attempt
    history or the quiz's participant count.

    Still requires a valid initData and still runs the premium/access gate,
    so it doesn't leak quiz existence or metadata to an unauthenticated or
    unauthorized caller -- same access rules as /api/session, just without
    the side effect of starting an attempt.
    """
    user_id, _ = await _authenticate(x_telegram_init_data)

    gate = await check_premium_gate(user_id, config.MINI_APP_REQUIRE_PREMIUM)
    if not gate.allowed:
        raise HTTPException(status_code=403, detail={"error": "access_denied", "reason": gate.reason})

    quiz = await QuizRepository(get_db()).get(qid)
    if not quiz or not quiz.get("questions"):
        raise HTTPException(status_code=404)

    access = await check_play_access(quiz, user_id)
    if not access.allowed:
        payload = {"error": "access_denied", "reason": access.reason}
        if access.batch:
            payload["batch"] = {
                "name": access.batch.get("name"),
                "description": access.batch.get("description"),
                "payment_link": access.batch.get("payment_link"),
                "contact_info": access.batch.get("contact_info"),
            }
        raise HTTPException(status_code=403, detail=payload)

    return {
        "quiz_name": quiz["quiz_name"],
        "total_questions": len(quiz["questions"]),
        "timer": quiz.get("timer", 60),
        "correct_marks": quiz.get("correct_marks", 1),
        "negative_marks": quiz.get("negative_marks", 0),
        "has_sections": bool(quiz.get("sections")),
    }


@router.post("/session")
async def create_session(
    body: StartSessionBody,
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
) -> dict:
    """Start a new play session for a quiz. Verifies identity, checks
    access (paid-quiz auth/batch), then returns the session's public state
    plus the per-session decryption key -- everything AFTER this point uses
    that key."""
    user_id, display_name = await _authenticate(x_telegram_init_data)

    if body.mode not in ("practice", "exam"):
        raise HTTPException(status_code=422)

    await UserRepository(get_db()).get_or_create(user_id)

    gate = await check_premium_gate(user_id, config.MINI_APP_REQUIRE_PREMIUM)
    if not gate.allowed:
        raise HTTPException(status_code=403, detail={"error": "access_denied", "reason": gate.reason})

    quiz = await QuizRepository(get_db()).get(body.qid)
    if not quiz:
        raise HTTPException(status_code=404)

    access = await check_play_access(quiz, user_id)
    if not access.allowed:
        payload = {"error": "access_denied", "reason": access.reason}
        if access.batch:
            payload["batch"] = {
                "name": access.batch.get("name"),
                "description": access.batch.get("description"),
                "payment_link": access.batch.get("payment_link"),
                "contact_info": access.batch.get("contact_info"),
            }
        raise HTTPException(status_code=403, detail=payload)

    # Clamp/validate player-chosen overrides server-side -- never trust the
    # client for values that feed directly into scoring or timers. None
    # stays None (meaning "use the quiz's saved value").
    overrides = player_service.SessionOverrides(
        timer=_clamp_optional_int(body.timer, lo=0, hi=3600),
        negative_marks=_clamp_optional_float(body.negative_marks, lo=0.0, hi=100.0),
        shuffle_questions=body.shuffle_questions,
        shuffle_options=body.shuffle_options,
    )

    session_state = await player_service.start_session(
        user_id, display_name, body.qid, body.mode, overrides=overrides
    )
    if session_state is None:
        raise HTTPException(status_code=404)

    bot_token = _require_bot_token()
    key = derive_session_key(bot_token, user_id, session_state["attempt_id"])

    return {
        **session_state,
        "session_key": base64.b64encode(key).decode("ascii"),
    }


@router.get("/question")
async def get_question(
    attempt_id: str,
    position: int,
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
) -> dict:
    """Fetch one question, answer stripped, encrypted with the session's key."""
    user_id, _ = await _authenticate(x_telegram_init_data)

    session = player_service.get_session(attempt_id)
    if session is None or session["user_id"] != user_id:
        raise HTTPException(status_code=404)

    question = player_service.public_question(session, position)
    if question is None:
        raise HTTPException(status_code=404)

    bot_token = _require_bot_token()
    key = derive_session_key(bot_token, user_id, attempt_id)
    return encrypt_json(question, key)


@router.post("/answer")
async def post_answer(
    body: AnswerBody,
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
) -> dict:
    """Submit an answer for one question. Returns correctness/explanation
    (practice mode reveals these immediately; exam mode still computes and
    stores them server-side, but the client is expected not to display them
    until the final review screen)."""
    user_id, _ = await _authenticate(x_telegram_init_data)

    session = player_service.get_session(body.attempt_id)
    if session is None or session["user_id"] != user_id:
        raise HTTPException(status_code=404)

    result = player_service.submit_answer(session, body.position, body.selected)
    if result is None:
        raise HTTPException(status_code=409)  # invalid position or already answered

    bot_token = _require_bot_token()
    key = derive_session_key(bot_token, user_id, body.attempt_id)
    return encrypt_json(result, key)


@router.post("/complete")
async def post_complete(
    body: CompleteBody,
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
) -> dict:
    """Finalize the attempt and return final results (+ full review in exam mode)."""
    user_id, _ = await _authenticate(x_telegram_init_data)

    session = player_service.get_session(body.attempt_id)
    if session is None or session["user_id"] != user_id:
        raise HTTPException(status_code=404)

    bot_token = _require_bot_token()
    key = derive_session_key(bot_token, user_id, body.attempt_id)

    result = await player_service.complete_session(body.attempt_id)
    if result is None:
        raise HTTPException(status_code=404)

    return encrypt_json(result, key)


def create_app() -> FastAPI:
    app = FastAPI(title="Quiz Player Mini App", docs_url=None, redoc_url=None)
    app.include_router(router)

    @app.get("/")
    async def landing_page() -> FileResponse:
        # A bare visit to the Mini App's domain (no /play path) used to
        # fall through to FastAPI's default 404 handler and show a bare
        # {"detail":"Not Found"} JSON blob -- confusing for anyone who
        # opens the domain directly instead of launching through the
        # bot's "Play" button. Serve a proper branded landing page
        # instead; real quiz launches never hit this route (they always
        # go through /play/{qid} or /play).
        return FileResponse(_STATIC_DIR / "landing.html")

    @app.get("/play/{qid}")
    async def play_page(qid: str, mode: str = "practice") -> FileResponse:
        # The qid/mode in the URL are cosmetic/bootstrapping only -- the
        # actual quiz fetch happens through the authenticated /api/session
        # call from JS after Telegram's WebApp SDK loads and initData is
        # available. Serving the same static shell for any qid is safe;
        # no quiz content is embedded in this HTML response.
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/play")
    async def play_page_bare() -> FileResponse:
        # A `?startapp=play_<qid>_<mode>` deep link (used on inline share
        # cards -- see mini_app_link.py's mini_app_startapp_url) launches
        # the Mini App at whichever URL is registered with @BotFather, NOT
        # at /play/<qid> -- the qid/mode travel separately as the
        # `start_param`. Register the Mini App's URL as this bare /play
        # path so both launch styles resolve to a real page; index.html's
        # boot() reads initDataUnsafe.start_param first and only falls
        # back to the /play/<qid> URL-path form if that's empty.
        return FileResponse(_STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    return app
