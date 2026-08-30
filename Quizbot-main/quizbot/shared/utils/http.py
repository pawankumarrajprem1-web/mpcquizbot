"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import aiohttp

_session: Optional[aiohttp.ClientSession] = None
_lock = asyncio.Lock()


async def get_session() -> aiohttp.ClientSession:
    global _session
    async with _lock:
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
    return _session


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


async def request_json(
    method: str, url: str, *, headers: dict | None = None, json_body: dict | None = None,
    params: dict | None = None, retries: int = 2,
) -> tuple[int, Any]:
    """Make an HTTP request and return (status_code, json_or_text_body).
    Retries on network errors / 5xx with a short backoff.
    """
    session = await get_session()
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            async with session.request(
                method, url, headers=headers, json=json_body, params=params
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    body = await resp.text()
                if resp.status >= 500 and attempt < retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                return resp.status, body
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
    raise last_exc or RuntimeError(f"Request to {url} failed after {retries} retries")
