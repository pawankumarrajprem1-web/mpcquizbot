"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import aiofiles


def html_to_memory_file(html: str, filename: str) -> tuple[io.BytesIO, str]:
    """Return an in-memory file-like object ready to pass to send_document,
    avoiding disk I/O entirely for typical-sized generated HTML reports.
    """
    buf = io.BytesIO(html.encode("utf-8"))
    buf.name = filename
    return buf, filename


async def write_temp_file(content: bytes, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "wb") as f:
        await f.write(content)


async def read_file(path: Path | str) -> bytes:
    async with aiofiles.open(path, "rb") as f:
        return await f.read()


async def remove_file(path: Path | str) -> None:
    """Best-effort async-friendly file removal (offloaded so it never blocks)."""
    import asyncio

    def _remove():
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    await asyncio.get_running_loop().run_in_executor(None, _remove)
