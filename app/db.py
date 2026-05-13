from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

from configs.configs import settings

logger = logging.getLogger(__name__)

_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    telegram_id    INTEGER PRIMARY KEY,
    username       TEXT,
    first_name     TEXT,
    language_code  TEXT,
    language       TEXT NOT NULL DEFAULT 'fa',
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plans (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    data_limit_gb  INTEGER NOT NULL,
    duration_days  INTEGER NOT NULL,
    user_limit     INTEGER NOT NULL DEFAULT 1,
    price          INTEGER NOT NULL,
    is_active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id         INTEGER NOT NULL,
    plan_id             INTEGER NOT NULL,
    price               INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending_receipt',
    config_name         TEXT,
    receipt_file_id     TEXT,
    admin_note          TEXT,
    marzban_username    TEXT,
    subscription_url    TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at         TEXT,
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id),
    FOREIGN KEY (plan_id)     REFERENCES plans(id)
);

CREATE INDEX IF NOT EXISTS idx_orders_status      ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_telegram_id ON orders(telegram_id);

CREATE TABLE IF NOT EXISTS bot_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        yield db


async def init_db() -> None:
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(_DDL)
        for migration_sql, description in [
            ("ALTER TABLE orders ADD COLUMN config_name TEXT", "orders.config_name"),
            ("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'fa'", "users.language"),
            ("ALTER TABLE plans ADD COLUMN user_limit INTEGER NOT NULL DEFAULT 1", "plans.user_limit"),
            ("ALTER TABLE plans ADD COLUMN data_limit_gb_new INTEGER", "plans.data_limit_gb_new"),
            ("ALTER TABLE users ADD COLUMN phone_number TEXT", "users.phone_number"),
            ("ALTER TABLE orders ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'card'", "orders.payment_method"),
            ("ALTER TABLE orders ADD COLUMN nowpayments_id TEXT", "orders.nowpayments_id"),
        ]:
            try:
                await db.execute(migration_sql)
                await db.commit()
                logger.info("Migrated: added %s", description)
            except Exception:
                pass
        # Migrate plans that still have a title column (old schema) — drop it gracefully
        try:
            async with db.execute("SELECT title FROM plans LIMIT 1") as _:
                pass
            # Title column still exists; copy data_limit_gb and drop title via recreate
            await db.executescript("""
                BEGIN;
                CREATE TABLE IF NOT EXISTS plans_new (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_limit_gb  INTEGER NOT NULL,
                    duration_days  INTEGER NOT NULL,
                    user_limit     INTEGER NOT NULL DEFAULT 1,
                    price          INTEGER NOT NULL,
                    is_active      INTEGER NOT NULL DEFAULT 1
                );
                INSERT INTO plans_new (id, data_limit_gb, duration_days, user_limit, price, is_active)
                    SELECT id, data_limit_gb, duration_days, COALESCE(user_limit, 1), price, is_active FROM plans;
                DROP TABLE plans;
                ALTER TABLE plans_new RENAME TO plans;
                COMMIT;
            """)
            logger.info("Migrated plans table: dropped title column")
        except Exception:
            pass
    logger.info("Database initialised at %s", settings.db_path)
