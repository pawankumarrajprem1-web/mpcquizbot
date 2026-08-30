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
from datetime import datetime, timedelta
from typing import Any

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from quizbot.database import QuizRepository, get_db
from quizbot.shared.utils import is_premium_user

from ..telegram_utils import safe_send_message

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")


class ScheduledQuizManager:
    """Tracks pending scheduled-quiz jobs and drives their launch via the
    shared AsyncIOScheduler instance."""

    def __init__(self, scheduler: AsyncIOScheduler) -> None:
        self.scheduler = scheduler
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def add(self, chat_id: int, qid: str, scheduled_time: datetime, created_by: int, ctx: ContextTypes.DEFAULT_TYPE) -> str:
        async with self._lock:
            job_id = f"quiz_{chat_id}_{qid}_{int(scheduled_time.timestamp())}"
            self.scheduler.add_job(
                self._run, trigger=DateTrigger(run_date=scheduled_time),
                args=[chat_id, qid, ctx], id=job_id, replace_existing=True,
            )
            self.jobs[job_id] = {
                "chat_id": chat_id, "quiz_id": qid, "scheduled_time": scheduled_time,
                "created_by": created_by, "created_at": datetime.now(IST),
            }
            return job_id

    async def remove(self, job_id: str) -> bool:
        async with self._lock:
            if job_id not in self.jobs:
                return False
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass
            del self.jobs[job_id]
            return True

    async def get_for_chat(self, chat_id: int) -> list[dict[str, Any]]:
        async with self._lock:
            return [{**v, "job_id": k} for k, v in self.jobs.items() if v["chat_id"] == chat_id]

    async def _run(self, chat_id: int, qid: str, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        from .setup_wizard import _launch_quiz_from_settings

        try:
            admin_id = None
            async with self._lock:
                for jid, info in list(self.jobs.items()):
                    if info["chat_id"] == chat_id and info["quiz_id"] == qid:
                        admin_id = info["created_by"]
                        self.jobs.pop(jid, None)
                        break
            admin_id = admin_id or chat_id

            quiz_repo = QuizRepository(get_db())
            quiz = await quiz_repo.get(qid)
            if not quiz:
                await safe_send_message(ctx, chat_id, f"❌ Scheduled quiz {qid} not found. Try /start {qid} manually.")
                return

            quiz["question_set_id"] = quiz["qid"]
            quiz["negative_marking"] = quiz.get("negative_marks", 0)
            quiz["correct_mark"] = quiz.get("correct_marks", 1)

            class _FakeUser:
                def __init__(self, uid: int) -> None:
                    self.id = uid
                    self.first_name = "Scheduled"
                    self.is_bot = False

            class _FakeChat:
                def __init__(self, cid: int) -> None:
                    self.id = cid
                    self.type = "group"

            class _FakeMessage:
                def __init__(self, cid: int) -> None:
                    self.chat_id = cid
                    self.chat = _FakeChat(cid)
                    self.from_user = _FakeUser(admin_id)
                    self.message_id = int(time.time())
                    self.message_thread_id = None

            class _FakeUpdate:
                def __init__(self, cid: int) -> None:
                    self.message = _FakeMessage(cid)
                    self.update_id = int(time.time())

            ps = {
                "quiz": quiz, "skip": 0, "protect": False, "chat_type": "group",
                "correct_mark": 1.0, "neg_mark": quiz.get("negative_marking", 0.0),
                "shuffle_q": bool(quiz.get("shuffle_questions", False)),
                "shuffle_o": bool(quiz.get("shuffle_options", False)),
                "timer_override": None, "initiator_id": admin_id,
                "update": _FakeUpdate(chat_id),
            }

            await safe_send_message(
                ctx, chat_id,
                f"\U0001F3AF <b>Scheduled Quiz Starting!</b>\n\nQuiz ID: <code>{qid}</code>\n"
                f"Started at: {datetime.now(IST).strftime('%I:%M %p')}\n"
                f"⏱ Timer: {quiz.get('timer', 30)}s | Questions: {len(quiz.get('questions', []))}",
                parse_mode=ParseMode.HTML,
            )
            await _launch_quiz_from_settings(chat_id, ctx, ps)
        except Exception as e:
            logger.error("Scheduled quiz exec error: %s", e, exc_info=True)
            try:
                await safe_send_message(ctx, chat_id, f"❌ Error starting scheduled quiz {qid}: {e}\nTry /start {qid}")
            except Exception:
                pass


schedule_mgr: "ScheduledQuizManager | None" = None


def init_schedule_manager(scheduler: AsyncIOScheduler) -> ScheduledQuizManager:
    """Called once from bot.py after the shared scheduler is created."""
    global schedule_mgr
    schedule_mgr = ScheduledQuizManager(scheduler)
    return schedule_mgr


async def schedule_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/schedule QUIZ_ID HH:MM` -- schedule a quiz to auto-launch today
    (or tomorrow if the time has already passed), IST."""
    chat_id = update.message.chat_id
    try:
        user_id = update.message.from_user.id
        if update.message.chat.type == ChatType.PRIVATE:
            await safe_send_message(ctx, chat_id, "❌ Groups only.")
            return

        try:
            member = await ctx.bot.get_chat_member(chat_id, user_id)
            if member.status not in ("administrator", "creator"):
                await safe_send_message(ctx, chat_id, "\U0001F6AB Admin only.")
                return
        except Exception:
            return

        if not await is_premium_user(user_id):
            await safe_send_message(ctx, chat_id, "\U0001F512 Premium required for scheduling.")
            return

        if len(ctx.args) < 2:
            await safe_send_message(
                ctx, chat_id,
                "\U0001F4C5 Usage: <code>/schedule QUIZ_ID HH:MM</code>\nExample: <code>/schedule ABC123 14:30</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        qid, time_str = ctx.args[0], ctx.args[1]
        try:
            h, m = map(int, time_str.split(":"))
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except Exception:
            await safe_send_message(ctx, chat_id, "❌ Invalid time. Use HH:MM (24h).")
            return

        now = datetime.now(IST)
        sched_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if sched_time <= now:
            sched_time += timedelta(days=1)

        quiz_repo = QuizRepository(get_db())
        quiz = await quiz_repo.get(qid)
        if not quiz:
            await safe_send_message(ctx, chat_id, f"❌ Quiz {qid} not found.")
            return

        await schedule_mgr.add(chat_id, qid, sched_time, user_id, ctx)

        diff = sched_time - now
        hrs, rem = divmod(int(diff.total_seconds()), 3600)
        mins, _ = divmod(rem, 60)
        await safe_send_message(
            ctx, chat_id,
            f"✅ <b>Scheduled!</b>\n\n\U0001F4DD {quiz.get('quiz_name', 'Quiz')}\n"
            f"\U0001F550 {sched_time.strftime('%I:%M %p, %d %b')}\n⏱️ In {hrs}h {mins}m",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error("schedule_command error: %s", e, exc_info=True)


async def viewschedule_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/viewschedule` -- lists this group's pending scheduled quizzes."""
    chat_id = update.message.chat_id
    try:
        if update.message.chat.type == ChatType.PRIVATE:
            await safe_send_message(ctx, chat_id, "❌ Groups only.")
            return

        schedules = await schedule_mgr.get_for_chat(chat_id)
        if not schedules:
            await safe_send_message(ctx, chat_id, "\U0001F4C5 No scheduled quizzes.")
            return

        schedules.sort(key=lambda x: x["scheduled_time"])
        now = datetime.now(IST)
        text = "\U0001F4C5 <b>Scheduled Quizzes</b>\n\n"
        for i, s in enumerate(schedules, 1):
            diff = s["scheduled_time"] - now
            if diff.total_seconds() > 0:
                h, r = divmod(int(diff.total_seconds()), 3600)
                m, _ = divmod(r, 60)
                until = f"{h}h {m}m"
            else:
                until = "Starting soon..."
            text += f"{i}. <code>{s['quiz_id']}</code>\n   \U0001F550 {s['scheduled_time'].strftime('%I:%M %p, %d %b')} (in {until})\n\n"
        await safe_send_message(ctx, chat_id, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("viewschedule_command error: %s", e)


async def cancelschedule_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/cancelschedule QUIZ_ID` -- cancels a pending scheduled quiz."""
    chat_id = update.message.chat_id
    try:
        user_id = update.message.from_user.id
        if update.message.chat.type == ChatType.PRIVATE:
            await safe_send_message(ctx, chat_id, "❌ Groups only.")
            return

        try:
            member = await ctx.bot.get_chat_member(chat_id, user_id)
            if member.status not in ("administrator", "creator"):
                await safe_send_message(ctx, chat_id, "\U0001F6AB Admin only.")
                return
        except Exception:
            return

        if not ctx.args:
            await safe_send_message(ctx, chat_id, "Usage: <code>/cancelschedule QUIZ_ID</code>", parse_mode=ParseMode.HTML)
            return

        qid = ctx.args[0]
        schedules = await schedule_mgr.get_for_chat(chat_id)
        for s in schedules:
            if s["quiz_id"] == qid and await schedule_mgr.remove(s["job_id"]):
                await safe_send_message(ctx, chat_id, f"✅ Schedule cancelled for {qid}.")
                return
        await safe_send_message(ctx, chat_id, f"❌ No schedule for {qid}.")
    except Exception as e:
        logger.error("cancelschedule_command error: %s", e)


def register(application: Application) -> None:
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("viewschedule", viewschedule_command))
    application.add_handler(CommandHandler("cancelschedule", cancelschedule_command))
