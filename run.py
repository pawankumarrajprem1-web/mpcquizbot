#!/usr/bin/env python3
"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from quizbot.database import init_db, close_db
from quizbot.shared import config
from quizbot.shared.utils.http import close_session                

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("launcher")

# Silence noisy third-party debug logs by default.
for noisy in ("httpx", "httpcore", "apscheduler", "pymongo"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


async def _run_creator_bot() -> None:
    from quizbot.creator_bot.bot import run_creator_bot

    logger.info("Starting Creator Bot (Pyrogram)...")
    await run_creator_bot()


async def _run_runner_bot() -> None:
    from quizbot.runner_bot.bot import run_runner_bot

    logger.info("Starting Runner Bot (python-telegram-bot)...")
    await run_runner_bot()


async def _run_mini_app() -> None:
    from quizbot.mini_app.server import run_mini_app_server

    logger.info("Starting Mini App server (FastAPI)...")
    await run_mini_app_server()


async def main(only: str | None) -> None:
    problems = config.validate(bot=only or "both")
    if problems:
        for p in problems:
            logger.error("Config problem: %s", p)
        logger.error("Fix the above in your .env file (see .env.example) before starting.")
        sys.exit(1)

    logger.info("Connecting to MongoDB (db=%s) ...", config.MONGODB_DB_NAME)
    await init_db(config.MONGODB_URI, config.MONGODB_DB_NAME)
    logger.info("Database ready.")

    tasks: list[asyncio.Task] = []
    if only in (None, "creator"):
        tasks.append(asyncio.create_task(_run_creator_bot(), name="creator_bot"))
    if only in (None, "runner"):
        tasks.append(asyncio.create_task(_run_runner_bot(), name="runner_bot"))
    # Force run mini app on Render to satisfy port checks
    tasks.append(asyncio.create_task(_run_mini_app(), name="mini_app"))
    stop_event = asyncio.Event()

    def _handle_signal(*_args):
        logger.info("Shutdown signal received, stopping bots...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass  # Windows

    try:
        done, pending = await asyncio.wait(
            [*tasks, asyncio.ensure_future(stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in done:
            if t.exception():
                logger.exception("A bot task crashed:", exc_info=t.exception())
    finally:
        logger.info("Shutting down...")
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_session()
        await close_db()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Advance Quiz Bot platform.")
    parser.add_argument(
        "--only", choices=["creator", "runner", "miniapp"], default=None,
        help="Run only one component (default: run both bots, plus the "
             "Mini App server too if MINI_APP_DOMAIN is configured).",
    )
    args = parser.parse_args()

    try:
        asyncio.run(main(args.only))
    except KeyboardInterrupt:
        pass
