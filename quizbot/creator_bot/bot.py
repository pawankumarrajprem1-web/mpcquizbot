"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import asyncio
import logging

from pyrogram import Client

from quizbot.shared import config

logger = logging.getLogger(__name__)


def build_client() -> Client:
    """Construct (but do not start) the Creator Bot's Pyrogram client."""
    return Client(
        "creator_bot",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.CREATOR_BOT_TOKEN,
        in_memory=True,
        workers=50,
    )


async def run_creator_bot(stop_event: asyncio.Event | None = None) -> None:
    """Start the Creator Bot and block until the process is asked to stop.

    Uses `app.start()` / (wait) / `app.stop()` explicitly rather than
    `Client.run()`, since `run()` calls `asyncio.get_event_loop().
    run_until_complete(...)` internally and would conflict with the Runner
    Bot also running in this same shared event loop.

    We intentionally do NOT call `pyrogram.idle()` here: that helper installs
    its own OS signal handlers and is meant for a single-bot process, which
    would conflict when the Runner Bot is also running as a sibling task in
    this process (see `quizbot/run.py`, which installs its own SIGINT/SIGTERM
    handling and cancels both bot tasks on shutdown). Instead we just await
    an `asyncio.Event` that the caller cancels/sets on shutdown -- if the
    caller doesn't supply one (e.g. running this bot standalone) we create
    one and wait on it forever, relying on task cancellation to stop us.
    """
    app = build_client()

    from .handlers import register

    register(app)

    await app.start()
    me = await app.get_me()
    logger.info("Creator Bot started as @%s", me.username)

    own_event = stop_event or asyncio.Event()
    try:
        await own_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Stopping Creator Bot...")
        await app.stop()
        logger.info("Creator Bot stopped.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_creator_bot())
