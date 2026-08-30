"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels above shared/: shared -> quizbot -> root).
_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_ROOT / ".env")


def _env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def _env_int(key: str, default: int | None = None) -> int | None:
    value = os.getenv(key)
    if value is None or value == "":
        return default
    return int(value)


def _env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int_list(key: str) -> list[int]:
    raw = os.getenv(key, "")
    return [int(x) for x in raw.replace(" ", "").split(",") if x]


# ---------------------------------------------------------------------------
# Telegram credentials
# ---------------------------------------------------------------------------
API_ID: int | None = _env_int("API_ID")
API_HASH: str | None = _env("API_HASH")

CREATOR_BOT_TOKEN: str | None = _env("CREATOR_BOT_TOKEN")
RUNNER_BOT_TOKEN: str | None = _env("RUNNER_BOT_TOKEN")

# ---------------------------------------------------------------------------
# Database (MongoDB Atlas -- a hosted database reachable over the network,
# so data survives dyno restarts/redeploys on ephemeral hosts like Heroku.
# The old local-SQLite-file setup lost all data on every restart there.
# Get a free connection string from https://cloud.mongodb.com (M0 free
# tier, 512MB, no time limit) -- see README.md for the exact setup steps.
# ---------------------------------------------------------------------------
MONGODB_URI: str | None = _env("MONGODB_URI")
MONGODB_DB_NAME: str = _env("MONGODB_DB_NAME", "quizbot")

# ---------------------------------------------------------------------------
# Ownership / admin access
# ---------------------------------------------------------------------------
OWNER_ID: int | None = _env_int("OWNER_ID")
ADMIN_IDS: list[int] = _env_int_list("ADMIN_IDS")

# ---------------------------------------------------------------------------
# Channels / groups
# ---------------------------------------------------------------------------
LOG_GROUP: int | None = _env_int("LOG_GROUP")
BOT_GROUP: int | None = _env_int("BOT_GROUP")
CHANNEL_ID: int | None = _env_int("CHANNEL_ID")
REQUIRED_SUB_CHANNEL: str | None = _env("REQUIRED_SUB_CHANNEL")

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
FREE_BOT: bool = _env_bool("FREE_BOT", False)

# ---------------------------------------------------------------------------
# Payments (Razorpay)
# ---------------------------------------------------------------------------
RAZORPAY_KEY_ID: str | None = _env("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET: str | None = _env("RAZORPAY_KEY_SECRET")

PLANS: dict[str, dict] = {
    "1_month": {"days": 30, "amount": _env_int("PLAN_1_MONTH_AMOUNT", 9900), "label": "1 Month"},
    "3_month": {"days": 90, "amount": _env_int("PLAN_3_MONTH_AMOUNT", 24900), "label": "3 Months"},
    "1_year": {"days": 365, "amount": _env_int("PLAN_1_YEAR_AMOUNT", 79900), "label": "1 Year"},
}

# ---------------------------------------------------------------------------
# PDF generation microservice (optional external service)
# ---------------------------------------------------------------------------
PDF_API_BASE: str | None = _env("PDF_API_BASE")

# ---------------------------------------------------------------------------
# Quiz Player Mini App (Telegram WebApp)
# ---------------------------------------------------------------------------
# The public HTTPS domain the Mini App is served from (e.g.
# "https://play.example.com") -- Telegram WebApp buttons REQUIRE a public
# HTTPS URL, so this must be reachable from the internet in production (a
# reverse proxy/tunnel in front of MINI_APP_HOST:MINI_APP_PORT). Leave blank
# to disable the "Play" buttons entirely (the bots skip adding them, and
# the server itself just won't be linked from anywhere).
MINI_APP_DOMAIN: str | None = _env("MINI_APP_DOMAIN")
MINI_APP_HOST: str = _env("MINI_APP_HOST", "0.0.0.0")
# Heroku (and most PaaS hosts) assign a random port per dyno and put it in
# $PORT -- the router ONLY forwards external traffic to that port, so it
# must take priority over MINI_APP_PORT/.env when present. Locally (no
# $PORT set) this falls back to MINI_APP_PORT / 8080 as before.
MINI_APP_PORT: int = _env_int("PORT") or _env_int("MINI_APP_PORT", 8080)
# Optional: gate the Mini App itself behind premium, independent of
# individual quiz pricing. Off by default.
MINI_APP_REQUIRE_PREMIUM: bool = _env_bool("MINI_APP_REQUIRE_PREMIUM", False)

# ---------------------------------------------------------------------------
# AI providers (fallback/default keys are opt-in via env; empty by default)
# ---------------------------------------------------------------------------
OPENROUTER_DEFAULT_KEYS: list[str] = [
    k for k in _env("OPENROUTER_DEFAULT_KEYS", "").split(",") if k
]
GEMINI_URL: str = _env(
    "GEMINI_URL",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
)
GROQ_URL: str = _env("GROQ_URL", "https://api.groq.com/openai/v1/chat/completions")
POLLINATIONS_URL: str = _env("POLLINATIONS_URL", "https://text.pollinations.ai/openai")

# ---------------------------------------------------------------------------
# Rate limiting / quiz tuning
# ---------------------------------------------------------------------------
# Runner Bot's general-purpose rate limiter (its rate limiting was a single
# generic window/max-requests pair in the original, unlike the Creator Bot's
# three named buckets below).
RATE_LIMIT_WINDOW: int = _env_int("RATE_LIMIT_WINDOW", 60)
RATE_LIMIT_MAX_REQUESTS: int = _env_int("RATE_LIMIT_MAX_REQUESTS", 20)
SESSION_TIMEOUT: int = _env_int("SESSION_TIMEOUT", 3600)
SESSION_CLEANUP_INTERVAL: int = _env_int("SESSION_CLEANUP_INTERVAL", 600)
# Matches the original quiz2.py hardcoded value: answers faster than this
# many seconds (and wrong) count toward the anti-cheat flag.
CHEAT_SPEED_THRESHOLD: float = float(_env("CHEAT_SPEED_THRESHOLD", "3.0"))
WATCHDOG_INTERVAL: int = _env_int("WATCHDOG_INTERVAL", 300)

# Creator Bot's three named rate-limit buckets (hits, window_seconds).
# Defaults match the original adv2.py's hardcoded RATE_LIMITS exactly:
#   default: 10 commands / 30 min, create: 4 / 30 min, strict: 1 / 60 min.
CREATOR_RATE_LIMIT_DEFAULT: tuple[int, int] = (
    _env_int("CREATOR_RATE_LIMIT_DEFAULT_HITS", 10),
    _env_int("CREATOR_RATE_LIMIT_DEFAULT_WINDOW", 1800),
)
CREATOR_RATE_LIMIT_CREATE: tuple[int, int] = (
    _env_int("CREATOR_RATE_LIMIT_CREATE_HITS", 4),
    _env_int("CREATOR_RATE_LIMIT_CREATE_WINDOW", 1800),
)
CREATOR_RATE_LIMIT_STRICT: tuple[int, int] = (
    _env_int("CREATOR_RATE_LIMIT_STRICT_HITS", 1),
    _env_int("CREATOR_RATE_LIMIT_STRICT_WINDOW", 3600),
)

PAGE_SIZE: int = _env_int("PAGE_SIZE", 10)
QUESTIONS_PER_PAGE: int = _env_int("QUESTIONS_PER_PAGE", 10)
LEADERS_PAGE_SIZE: int = _env_int("LEADERS_PAGE_SIZE", 20)
CACHE_EXPIRY: int = _env_int("CACHE_EXPIRY", 600)

SUPPORTED_AI_PROVIDERS: list[str] = ["gemini", "groq", "openrouter", "openai", "mistral", "pollinations"]

# ---------------------------------------------------------------------------
# Local storage directories (relative to project root)
# ---------------------------------------------------------------------------
DATA_DIR: Path = _ROOT / "data"
CACHE_DIR: Path = DATA_DIR / "cache"
TEMP_DIR: Path = DATA_DIR / "tmp"

for _d in (DATA_DIR, CACHE_DIR, TEMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def validate(bot: str = "both") -> list[str]:
    """Return a list of human-readable problems with the current config.

    `bot` may be 'creator', 'runner', 'miniapp', or 'both' to scope which
    token is required.
    """
    problems = []
    if not MONGODB_URI:
        problems.append("MONGODB_URI is not set (get a free connection string from https://cloud.mongodb.com)")
    if bot == "miniapp":
        # The Mini App only needs to verify initData signed by whichever bot
        # opened it, so at least one token is enough (not both).
        if not CREATOR_BOT_TOKEN and not RUNNER_BOT_TOKEN:
            problems.append("CREATOR_BOT_TOKEN or RUNNER_BOT_TOKEN must be set (Mini App verifies initData against one of them)")
        return problems
    if not API_ID or not API_HASH:
        problems.append("API_ID / API_HASH are required (get them from my.telegram.org)")
    if bot in ("creator", "both") and not CREATOR_BOT_TOKEN:
        problems.append("CREATOR_BOT_TOKEN is not set")
    if bot in ("runner", "both") and not RUNNER_BOT_TOKEN:
        problems.append("RUNNER_BOT_TOKEN is not set")
    if not OWNER_ID:
        problems.append("OWNER_ID is not set (owner-only commands will be unreachable)")
    return problems
