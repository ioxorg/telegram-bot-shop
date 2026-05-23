from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Telegram
    bot_token: str
    admin_telegram_id: int

    # Marzban
    marzban_base_url: str
    marzban_username: str
    marzban_password: str

    # Payment — used only for the one-time DB seed on first run.
    # After that, values live in the bot_settings DB table.
    initial_card_number: str
    initial_card_holder_name: str
    initial_currency_label: str

    # Static text
    how_to_connect_text: str
    support_url: str
    welcome_sticker_id: str  # optional — empty string = no sticker

    # NOWPayments — optional, empty string = disabled
    nowpayments_api_key: str
    nowpayments_email: str
    nowpayments_password: str

    # Proxy — socks5h://user:pass@host:port (empty = direct)
    telegram_proxy_url: str

    # Database backend — "sqlite" (default) or "postgres"
    db_backend: str
    # SQLite — only used when db_backend == "sqlite"
    db_path: str
    # PostgreSQL DSN — only used when db_backend == "postgres"
    # e.g. postgresql://user:pass@localhost:5432/shopdb
    database_url: str

    log_level: str


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def load_settings() -> Settings:
    return Settings(
        bot_token=_require("BOT_TOKEN"),
        admin_telegram_id=int(_require("ADMIN_TELEGRAM_ID")),
        marzban_base_url=_require("MARZBAN_BASE_URL").rstrip("/"),
        marzban_username=_require("MARZBAN_USERNAME"),
        marzban_password=_require("MARZBAN_PASSWORD"),
        initial_card_number=os.getenv("CARD_NUMBER", ""),
        initial_card_holder_name=os.getenv("CARD_HOLDER_NAME", ""),
        initial_currency_label=os.getenv("CURRENCY_LABEL", "تومان"),
        how_to_connect_text=os.getenv(
            "HOW_TO_CONNECT_TEXT",
            "Install v2rayNG / NekoBox / Streisand and paste your link.",
        ),
        support_url=os.getenv("SUPPORT_URL", ""),
        welcome_sticker_id=os.getenv("WELCOME_STICKER_ID", ""),
        nowpayments_api_key=os.getenv("NOWPAYMENTS_API_KEY", ""),
        nowpayments_email=os.getenv("NOWPAYMENTS_EMAIL", ""),
        nowpayments_password=os.getenv("NOWPAYMENTS_PASSWORD", ""),
        telegram_proxy_url=os.getenv("TELEGRAM_PROXY_URL", ""),
        db_backend=os.getenv("DB_BACKEND", "sqlite").lower(),
        db_path=os.getenv("DB_PATH", "data/shop.db"),
        database_url=os.getenv("DATABASE_URL", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


settings: Settings = load_settings()
