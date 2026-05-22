#!/usr/bin/env python3
"""
One-time migration: copy all data from SQLite → PostgreSQL.

The script is idempotent — it uses ON CONFLICT DO NOTHING so re-running it
safely skips rows that already exist in PostgreSQL.

Usage
-----
Set the following environment variables (or put them in .env), then run:

    python scripts/migrate_sqlite_to_postgres.py

Required env vars:
    DATABASE_URL   — PostgreSQL DSN, e.g. postgresql://shop:secret@localhost/shopdb

Optional env vars:
    DB_PATH        — path to the SQLite file (default: data/shop.db)

What it does
------------
1. Reads every row from users, plans, orders, bot_settings in SQLite.
2. Creates the PostgreSQL schema (CREATE TABLE IF NOT EXISTS …).
3. Inserts rows with ON CONFLICT DO NOTHING (safe to re-run).
4. Resets the SERIAL sequences for plans and orders so new inserts get
   correct ids after the migration.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── PostgreSQL DDL (mirrors app/db.py _PG_DDL) ───────────────────────────────

_PG_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS users (
        telegram_id    BIGINT PRIMARY KEY,
        username       TEXT,
        first_name     TEXT,
        language_code  TEXT,
        language       TEXT NOT NULL DEFAULT 'fa',
        phone_number   TEXT,
        created_at     TEXT NOT NULL
                           DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS plans (
        id             SERIAL PRIMARY KEY,
        data_limit_gb  INTEGER NOT NULL,
        duration_days  INTEGER NOT NULL,
        user_limit     INTEGER NOT NULL DEFAULT 1,
        price          INTEGER NOT NULL,
        is_active      INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        id                  SERIAL PRIMARY KEY,
        telegram_id         BIGINT  NOT NULL REFERENCES users(telegram_id),
        plan_id             INTEGER NOT NULL REFERENCES plans(id),
        price               INTEGER NOT NULL,
        status              TEXT NOT NULL DEFAULT 'pending_receipt',
        config_name         TEXT,
        receipt_file_id     TEXT,
        admin_note          TEXT,
        marzban_username    TEXT,
        subscription_url    TEXT,
        payment_method      TEXT NOT NULL DEFAULT 'card',
        nowpayments_id      TEXT,
        created_at          TEXT NOT NULL
                                DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
        reviewed_at         TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_orders_status      ON orders(status)",
    "CREATE INDEX IF NOT EXISTS idx_orders_telegram_id ON orders(telegram_id)",
    """
    CREATE TABLE IF NOT EXISTS bot_settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT ''
    )
    """,
]


# ── Main migration ─────────────────────────────────────────────────────────────

async def migrate() -> None:
    import aiosqlite
    import asyncpg

    db_path = os.getenv("DB_PATH", "data/shop.db")
    database_url = os.getenv("DATABASE_URL", "")

    if not database_url:
        logger.error("DATABASE_URL is not set. Aborting.")
        sys.exit(1)

    if not os.path.exists(db_path):
        logger.error("SQLite file not found: %s", db_path)
        sys.exit(1)

    logger.info("Source: SQLite  → %s", db_path)
    logger.info("Target: Postgres → %s", database_url.split("@")[-1])

    # ── 1. Read all data from SQLite ──────────────────────────────────────────
    logger.info("Reading SQLite data …")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("SELECT telegram_id, username, first_name, language_code, language, phone_number, created_at FROM users") as cur:
            users = await cur.fetchall()

        # Exclude data_limit_gb_new (leftover migration artefact)
        async with db.execute("SELECT id, data_limit_gb, duration_days, user_limit, price, is_active FROM plans") as cur:
            plans = await cur.fetchall()

        async with db.execute(
            "SELECT id, telegram_id, plan_id, price, status, config_name, "
            "receipt_file_id, admin_note, marzban_username, subscription_url, "
            "payment_method, nowpayments_id, created_at, reviewed_at FROM orders"
        ) as cur:
            orders = await cur.fetchall()

        async with db.execute("SELECT key, value FROM bot_settings") as cur:
            settings_rows = await cur.fetchall()

    logger.info(
        "Read: %d users, %d plans, %d orders, %d settings",
        len(users), len(plans), len(orders), len(settings_rows),
    )

    # ── 2. Connect to PostgreSQL and create schema ────────────────────────────
    logger.info("Connecting to PostgreSQL …")
    pg = await asyncpg.connect(database_url)

    try:
        async with pg.transaction():
            logger.info("Creating schema (if not exists) …")
            for stmt in _PG_DDL:
                await pg.execute(stmt)

        # ── 3. Insert data ────────────────────────────────────────────────────

        # users
        logger.info("Migrating users …")
        async with pg.transaction():
            for row in users:
                await pg.execute(
                    """
                    INSERT INTO users
                        (telegram_id, username, first_name, language_code, language, phone_number, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT DO NOTHING
                    """,
                    row["telegram_id"], row["username"], row["first_name"],
                    row["language_code"], row["language"] or "fa",
                    row["phone_number"], row["created_at"],
                )
        logger.info("  → %d users inserted (duplicates skipped)", len(users))

        # plans — insert with explicit id so orders' FK references are preserved
        logger.info("Migrating plans …")
        async with pg.transaction():
            for row in plans:
                await pg.execute(
                    """
                    INSERT INTO plans
                        (id, data_limit_gb, duration_days, user_limit, price, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT DO NOTHING
                    """,
                    row["id"], row["data_limit_gb"], row["duration_days"],
                    row["user_limit"], row["price"], row["is_active"],
                )
        logger.info("  → %d plans inserted (duplicates skipped)", len(plans))

        # orders — insert with explicit id
        logger.info("Migrating orders …")
        async with pg.transaction():
            for row in orders:
                await pg.execute(
                    """
                    INSERT INTO orders
                        (id, telegram_id, plan_id, price, status, config_name,
                         receipt_file_id, admin_note, marzban_username, subscription_url,
                         payment_method, nowpayments_id, created_at, reviewed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    ON CONFLICT DO NOTHING
                    """,
                    row["id"], row["telegram_id"], row["plan_id"], row["price"],
                    row["status"], row["config_name"], row["receipt_file_id"],
                    row["admin_note"], row["marzban_username"], row["subscription_url"],
                    row["payment_method"] or "card", row["nowpayments_id"],
                    row["created_at"], row["reviewed_at"],
                )
        logger.info("  → %d orders inserted (duplicates skipped)", len(orders))

        # bot_settings
        logger.info("Migrating bot_settings …")
        async with pg.transaction():
            for row in settings_rows:
                await pg.execute(
                    """
                    INSERT INTO bot_settings (key, value) VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                    """,
                    row["key"], row["value"],
                )
        logger.info("  → %d settings inserted (duplicates skipped)", len(settings_rows))

        # ── 4. Reset SERIAL sequences ─────────────────────────────────────────
        # After inserting with explicit ids, the sequences are still at their
        # initial value (1). Reset them to MAX(id) so the next auto-insert
        # doesn't collide.
        logger.info("Resetting sequences …")
        async with pg.transaction():
            await pg.execute(
                "SELECT setval('plans_id_seq', COALESCE((SELECT MAX(id) FROM plans), 0))"
            )
            await pg.execute(
                "SELECT setval('orders_id_seq', COALESCE((SELECT MAX(id) FROM orders), 0))"
            )
        logger.info("  → sequences reset")

    finally:
        await pg.close()

    logger.info("Migration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
