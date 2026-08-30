"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging

import uvicorn

from quizbot.shared import config

from .routes import create_app

logger = logging.getLogger(__name__)


async def run_mini_app_server() -> None:
    """Start the Mini App HTTP server and run until cancelled."""
    if not config.MINI_APP_DOMAIN:
        logger.warning(
            "MINI_APP_DOMAIN is not set -- the Mini App server will still "
            "start (for local testing), but bot 'Play' buttons will be "
            "skipped since no public URL is configured. Set MINI_APP_DOMAIN "
            "in .env to enable them."
        )

    app = create_app()
    uv_config = uvicorn.Config(
        app,
        host=config.MINI_APP_HOST,
        port=config.MINI_APP_PORT,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(uv_config)
    logger.info(
        "Mini App server starting on %s:%s", config.MINI_APP_HOST, config.MINI_APP_PORT
    )
    await server.serve()
