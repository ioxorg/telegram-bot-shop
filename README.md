# Marzban VPN Shop — Telegram Bot

A Telegram bot that sells Marzban VPN subscriptions via card-to-card bank transfer.

## Features

- Plan browsing with inline buttons
- Card-to-card payment with receipt photo upload
- Admin approval / rejection workflow via inline buttons
- Automatic Marzban user creation on approval
- Subscription link delivery to buyer
- SQLite persistence — no state lost on restart

---

## Setup

### 1. Prerequisites

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) installed
- A running Marzban panel
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))

### 2. Install dependencies

```bash
uv venv
uv sync
```

### 3. Configure `.env`

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Required values:

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Token from BotFather |
| `ADMIN_TELEGRAM_ID` | Your Telegram numeric user ID (get it from @userinfobot) |
| `MARZBAN_BASE_URL` | Full URL of your Marzban panel, e.g. `https://panel.example.com` |
| `MARZBAN_USERNAME` | Marzban admin username |
| `MARZBAN_PASSWORD` | Marzban admin password |
| `CARD_NUMBER` | Bank card number shown to buyers |
| `CARD_HOLDER_NAME` | Cardholder name shown to buyers |

Optional values have sensible defaults — see `.env.example`.

### 4. Plans

Plans are seeded from `PLAN_1`, `PLAN_2`, … env vars on first run (when the `plans` table is empty).
Format: `TITLE | DAYS | DATA_GB | PRICE`

```
PLAN_1=1 Month — 50 GB | 30 | 50 | 150000
```

To re-seed with new plans, clear the `plans` table in `data/shop.db` and restart.

### 5. Run

```bash
python app.py
```

Logs go to stdout. Set `LOG_LEVEL=DEBUG` for verbose output.

---

## Admin workflow

Once a user uploads a receipt, the admin (the Telegram ID in `ADMIN_TELEGRAM_ID`) receives the photo with two inline buttons:

- **✅ Approve** — creates the Marzban user and sends the subscription link to the buyer.
- **❌ Reject** — prompts the admin for a rejection reason, then DMs the buyer.

### Admin commands

| Command | Description |
|---|---|
| `/pending` | List orders awaiting review |
| `/stats` | User count, approved orders, total revenue |
| `/failed_orders` | Orders where Marzban creation failed |

---

## Project structure

```
app/
  handlers/     — aiogram routers (start, plans, purchase, my_subs, admin, static)
  repo/         — database access layer (users, plans, orders)
  bot.py        — dispatcher setup and run loop
  db.py         — SQLite init + schema
  keyboards.py  — all InlineKeyboardMarkup builders
  marzban.py    — Marzban API wrapper
  states.py     — FSM state groups
configs/
  configs.py    — typed Settings loaded from .env
app.py          — entry point
data/shop.db    — SQLite database (auto-created, gitignored)
```
