"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from pyrogram import Client, filters
from pyrogram.types import Message

from quizbot.database import AIKeyRepository, get_db
from quizbot.shared import config
from quizbot.shared.utils import is_premium_user

from ..ratelimit import ratelimit

logger = logging.getLogger(__name__)

PROVIDER_INFO: dict[str, str] = {
    "gemini": "Gemini 2.5 Flash -- free key at aistudio.google.com",
    "groq": "Groq Llama-3.3-70B -- fastest free tier, key at console.groq.com",
    "openrouter": "OpenRouter -- many free models, key at openrouter.ai",
    "openai": "OpenAI GPT-4o-mini -- key at platform.openai.com",
    "mistral": "Mistral Small -- key at console.mistral.ai",
    "pollinations": "Pollinations -- no key required (fallback)",
}


@ratelimit("default")
async def setkey_cmd(c: Client, m: Message) -> None:
    """/setkey <provider> <api_key> -- save a personal AI provider key."""
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("Premium required: /pay")
        return
    args = m.text.strip().split(maxsplit=2)
    if len(args) < 3:
        info = "\n".join(f"`{p}` -- {d}" for p, d in PROVIDER_INFO.items())
        await m.reply(
            "**Add AI API Key**\n\n"
            "Usage: `/setkey <provider> <api_key>`\n"
            "You can add multiple keys per provider.\n\n"
            f"**Providers:**\n{info}"
        )
        return
    provider = args[1].strip().lower()
    api_key = args[2].strip()
    if provider not in config.SUPPORTED_AI_PROVIDERS:
        await m.reply(f"Unknown provider. Use: {' | '.join(config.SUPPORTED_AI_PROVIDERS)}")
        return

    repo = AIKeyRepository(get_db())
    await repo.add(uid, provider, api_key)
    try:
        await m.delete()  # keep the raw key out of chat history
    except Exception:
        logger.debug("Could not delete /setkey message (missing permission?)")

    existing = await repo.list_for_provider(uid, provider)
    await m.reply(
        f"**{provider.title()} key #{len(existing)} added!**\n"
        f"Preview: `{api_key[:8]}...`\n"
        f"You now have **{len(existing)}** key(s) for {provider}.\n\n"
        f"Use /mykeys to see all."
    )


@ratelimit("default")
async def mykeys_cmd(c: Client, m: Message) -> None:
    """/mykeys -- list saved AI provider keys, grouped by provider."""
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("Premium required: /pay")
        return
    keys = await AIKeyRepository(get_db()).list_for_user(uid)
    if not keys:
        info = "\n".join(f"`{p}` -- {d}" for p, d in PROVIDER_INFO.items())
        await m.reply(f"No AI keys saved.\n\nAdd one with `/setkey <provider> <api_key>`\n\n{info}")
        return

    by_provider: dict[str, list[dict]] = defaultdict(list)
    for k in keys:
        by_provider[k["provider"]].append(k)

    lines = ["**Your AI Keys:**\n"]
    for provider, provider_keys in sorted(by_provider.items()):
        lines.append(f"**{provider.title()}** ({len(provider_keys)} key(s)):")
        for k in provider_keys:
            fail = f" ({k['fail_count']} fails)" if k.get("fail_count", 0) > 0 else ""
            preview = (k.get("api_key") or "")[:8]
            lines.append(f"  - ID `{k['id']}` -- `{preview}...`{fail}")
    lines.append("\nDelete: `/delkey <provider>` | `/delkey id <id>` | `/delkey all`")
    await m.reply("\n".join(lines))


@ratelimit("default")
async def delkey_cmd(c: Client, m: Message) -> None:
    """/delkey <provider>|id <key_id>|all -- delete saved AI keys."""
    uid = m.from_user.id
    if not await is_premium_user(uid):
        await m.reply("Premium required: /pay")
        return
    args = m.text.strip().split(maxsplit=2)
    if len(args) < 2:
        await m.reply("Usage: `/delkey <provider>` | `/delkey id <key_id>` | `/delkey all`")
        return

    repo = AIKeyRepository(get_db())
    target = args[1].strip().lower()

    if target == "all":
        await repo.delete_all(uid)
        await m.reply("Deleted all your AI keys.")
    elif target == "id" and len(args) == 3:
        key_id = args[2].strip()
        try:
            await repo.delete_by_id(uid, key_id)
        except Exception:
            await m.reply("Invalid key ID. Use /mykeys to see IDs.")
            return
        await m.reply(f"Key `{key_id}` deleted.")
    elif target in config.SUPPORTED_AI_PROVIDERS:
        await repo.delete_by_provider(uid, target)
        await m.reply(f"Deleted all {target.title()} key(s).")
    else:
        await m.reply("Unknown target. Use: `/delkey all` | `/delkey id <id>` | `/delkey <provider>`")


def register(app: Client) -> None:
    app.on_message(filters.command("setkey") & filters.private)(setkey_cmd)
    app.on_message(filters.command("mykeys") & filters.private)(mykeys_cmd)
    app.on_message(filters.command("delkey") & filters.private)(delkey_cmd)
