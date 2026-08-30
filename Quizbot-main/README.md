<div align="center">

# 🎯 Quizbot

**A production-grade Telegram quiz platform — create, manage, and run interactive quizzes at scale.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Pyrogram](https://img.shields.io/badge/Pyrogram-2.0-009485?logo=telegram)](https://pyrogram.org)
[![PTB](https://img.shields.io/badge/python--telegram--bot-22.8-0088CC?logo=telegram)](https://python-telegram-bot.org)
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?logo=mongodb)](https://mongodb.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://docker.com)

---

**Originally developed by [devgagan](https://github.com/devgaganin) &nbsp;•&nbsp; Sponsored by [Qzio](https://qzio.in)**

---

### 🤖 Try the Live Bot → [@advance_quiz_bot](https://t.me/advance_quiz_bot)

</div>

---

## 📋 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Prerequisites](#-prerequisites)
- [Quick Start](#-quick-start)
- [Configuration Reference](#-configuration-reference)
- [Running the Platform](#-running-the-platform)
  - [Run Everything](#run-everything)
  - [Run One Component Only](#run-one-component-only)
  - [systemd (VPS, always-on)](#systemd-vps-always-on)
- [Docker Deployment](#-docker-deployment)
- [Mini App — the Visual Quiz Player](#-mini-app--the-visual-quiz-player)
- [Database](#-database)
- [Credits](#-credits)

---

## ✨ Features

| Category | Capability |
|---|---|
| **Quiz Creation** | Text input, forwarded Telegram quiz polls, file/PDF import, AI-generated quizzes |
| **Quiz Formats** | Standard, sectional (per-section timers), practice & exam modes |
| **Smart Filtering** | Strips `[1/100]`-style progress tags, usernames, links, and custom word lists from imported polls |
| **Editing** | Shuffle questions, retitle, adjust timers, add/remove questions |
| **Access Control** | Free and paid quiz tiers, batch access, auth-chat lists, optional premium gate |
| **Analytics** | Per-user performance, leaderboards, sectional score breakdowns |
| **HTML Reports** | Self-contained interactive HTML scorecards — question navigator, KaTeX/Markdown rendering, dark/light theme |
| **Mini App** | Visual in-Telegram quiz player (practice + exam mode) as a Telegram WebApp |
| **Inline Sharing** | Share any quiz by ID via inline query, with a working Play button |
| **Payments** | Razorpay-backed premium plans |
| **Broadcast** | Send announcements to all users (owner only) |

---

## 🏗 Architecture

```
quizbot/
├── database/            Shared async MongoDB layer
│   ├── db.py             Motor connection manager + automatic index setup
│   └── repositories.py   One repository class per domain (users, quizzes, payments, ...)
│
├── shared/               Code shared by both bots
│   ├── config.py          All configuration & secrets, loaded from .env
│   ├── utils/             Text cleanup, premium checks, async file I/O
│   └── html/              Quiz-report HTML generator (exam UI + analysis)
│
├── creator_bot/          Pyrogram bot — quiz creation, editing, batches, payments
│   ├── bot.py             Client setup + run_creator_bot()
│   └── handlers/          One module per feature area
│
├── runner_bot/           python-telegram-bot bot — playing quizzes, AI generation
│   ├── bot.py             Application setup + run_runner_bot()
│   └── handlers/          One module per feature area
│
└── mini_app/             FastAPI Mini App — the visual "Play" quiz player
    ├── telegram_auth.py   Verifies Telegram WebApp initData (HMAC-SHA256)
    ├── player_service.py  Play-session state, scoring, DB persistence
    ├── routes.py          FastAPI app + /api/* endpoints
    └── static/index.html  Single-file frontend (practice + exam mode UI)

run.py                  Combined launcher — starts both bots (+ Mini App, if configured)
requirements.txt
Procfile                 Heroku process declaration (single web dyno)
Dockerfile / docker-compose.yml
.env.example             Environment variable template
```

Everything runs from **one process** (`run.py`) by default, sharing a single async MongoDB database:

- **Creator Bot** (Pyrogram) handles quiz creation, editing, imports, batches, and payments.
- **Runner Bot** (python-telegram-bot) handles quiz sessions — sending polls, tracking answers, building leaderboards.
- **Mini App** (FastAPI, optional) serves a visual in-Telegram quiz player when a public domain is configured.

---

## 🔧 Prerequisites

| Requirement | Minimum Version | Notes |
|---|---|---|
| Python | 3.11+ | |
| MongoDB | Atlas free tier (M0) or self-hosted | `MONGODB_URI` in `.env` |
| Telegram API credentials | — | From [my.telegram.org](https://my.telegram.org) |
| Two Telegram bot tokens | — | same token for both runner and creator u can keep seperate too|

---

## ⚡ Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env          # fill in your values — see Configuration Reference below

python run.py
```

The database and all its indexes are created automatically on first connect — no manual schema step needed.

---

## ⚙️ Configuration Reference

All values live in `.env` (copy from [`.env.example`](.env.example)). Note: you must not expose these values in the repo you fork directly otherwise you may loose your bot, data (securely fill these vars and secret in the environment of the platform you are using) 

| Variable | Required | Description |
|---|---|---|
| `API_ID` / `API_HASH` | ✅ | Telegram API credentials from [my.telegram.org](https://my.telegram.org) |
| `CREATOR_BOT_TOKEN` | ✅ | Token for the Pyrogram bot (creation, editing, payments) |
| `RUNNER_BOT_TOKEN` | ✅ | Token for the PTB bot (playing, scheduling, AI generation) |
| `MONGODB_URI` | ✅ | MongoDB Atlas connection string |
| `MONGODB_DB_NAME` | ✅ | Database name (default: `quizbot`) |
| `OWNER_ID` | ✅ | Your Telegram user ID |
| `ADMIN_IDS` | ➖ | Space-separated additional admin user IDs |
| `LOG_GROUP` | ➖ | Negative chat ID for error/log channel |
| `BOT_GROUP` | ➖ | Main community group ID |
| `CHANNEL_ID` | ➖ | Announcement channel ID |
| `REQUIRED_SUB_CHANNEL` | ➖ | Channel users must join to use `/start`, `/create`, `/myquizzes`, `/add` |
| `FREE_BOT` | ➖ | `true` to treat every user as premium |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | ➖ | Leave blank to disable the `/pay` premium-purchase flow |
| `PDF_API_BASE` | ➖ | Optional external PDF-generation microservice for `/testseries` |
| `MINI_APP_DOMAIN` | ➖ | Public HTTPS URL for the Mini App — leave blank to disable it entirely |
| `MINI_APP_HOST` / `MINI_APP_PORT` | ➖ | Local bind address behind your reverse proxy (default `0.0.0.0:8080`) |
| `OPENROUTER_DEFAULT_KEYS` | ➖ | Comma-separated fallback AI provider keys |

Rate limits, session timeouts, and other tuning knobs have sensible defaults — see the comments in `.env.example` for the full list.

---

## 🚀 Running the Platform

### Run Everything

```bash
python run.py
```

Starts both bots, and the Mini App server too if `MINI_APP_DOMAIN` is set.

### Run One Component Only

```bash
python run.py --only creator   # Creator Bot only
python run.py --only runner    # Runner Bot only
python run.py --only miniapp   # Mini App server only
```

### systemd (VPS, always-on)

```bash
sudo nano /etc/systemd/system/quizbot.service
```

```ini
[Unit]
Description=Quizbot Platform
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/quizbot
ExecStart=/opt/quizbot/.venv/bin/python run.py
Restart=always
RestartSec=10
EnvironmentFile=/opt/quizbot/.env
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now quizbot
sudo journalctl -u quizbot -f      # live logs
```

---

## 🐳 Docker Deployment

```bash
docker compose up -d --build
```

This starts the Creator Bot, Runner Bot, and (if `MINI_APP_DOMAIN` is set) the Mini App as separate containers, each connecting out to the same MongoDB Atlas cluster via `MONGODB_URI` — no local volume needed, since nothing is stored on the container's own filesystem.

To skip the Mini App entirely:

```bash
docker compose up -d --build creator-bot runner-bot
```

**Heroku / other PaaS**: a single `Procfile` (`web: python run.py`) runs the whole platform from one dyno/process — set the same `.env` variables as Config Vars.

---

## 📱 Mini App — the Visual Quiz Player

A "Play" button (opened as a Telegram WebApp) appears after quiz creation and on inline-share cards, offering two modes:

- **Practice mode** — instant correct/incorrect feedback with the explanation shown right after each answer, then auto-advance.
- **Exam mode** — no answers revealed until the end, followed by a full top-to-bottom review of every question, your answer, the correct answer, and the explanation.

It's strictly a player — no creation or editing happens here, and it enforces the same access rules as both bots (free/paid quizzes, batch access, auth-chat lists, optional premium gate).

Telegram requires a public HTTPS URL for WebApp buttons, so put a reverse proxy or tunnel (nginx, Caddy, Cloudflare Tunnel, etc.) in front of the FastAPI server and set `MINI_APP_DOMAIN` accordingly. Leave it blank to disable the feature entirely — no Play buttons are shown, and the server doesn't start.

Identity comes solely from Telegram's own `initData`, verified server-side via HMAC-SHA256 on every request. Quiz content in every API response is AES-256-GCM encrypted with a per-session key, and the correct answer is never present in a question's payload before it's answered.

---

## 🗄 Database

Data lives in MongoDB Atlas — a free M0 cluster is enough to get started (see [Quick Start](#-quick-start)). `quizbot/database/db.py` connects via Motor and creates every required index automatically on first connect, so there's no manual schema step. Both bots read and write through repository classes in `quizbot/database/repositories.py` — there's no separate API layer to keep in sync.

---

## 🙏 Credits

<div align="center">

| Role | |
|---|---|
| **Originally developed by** | [devgagan](https://github.com/devgaganin) |
| **Sponsored by** | [Qzio](https://qzio.in) — The Smart Quiz Platform |
| **Telegram Libraries** | [Pyrogram](https://pyrogram.org) & [python-telegram-bot](https://python-telegram-bot.org) |
| **Database** | [MongoDB Atlas](https://mongodb.com) |

---

*Built for educators, exam aspirants, and quiz creators.*

</div>
