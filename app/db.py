from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from configs.configs import settings

logger = logging.getLogger(__name__)

# ── Abstract connection interface ─────────────────────────────────────────────

class DbConn(ABC):
    """Normalised database connection — works for both SQLite and PostgreSQL."""

    @abstractmethod
    async def fetchone(self, query: str, params: tuple = ()) -> Any | None: ...

    @abstractmethod
    async def fetchall(self, query: str, params: tuple = ()) -> list[Any]: ...

    @abstractmethod
    async def execute(self, query: str, params: tuple = ()) -> None: ...

    @abstractmethod
    async def execute_returning_id(self, query: str, params: tuple = ()) -> int:
        """Execute an INSERT and return the new row's id."""
        ...

    @abstractmethod
    async def commit(self) -> None: ...


# ── SQLite backend ─────────────────────────────────────────────────────────────

_SQLITE_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    telegram_id    INTEGER PRIMARY KEY,
    username       TEXT,
    first_name     TEXT,
    language_code  TEXT,
    language       TEXT NOT NULL DEFAULT 'fa',
    phone_number   TEXT,
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
    payment_method      TEXT NOT NULL DEFAULT 'card',
    nowpayments_id      TEXT,
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

CREATE TABLE IF NOT EXISTS sales_reps (
    telegram_id    INTEGER PRIMARY KEY,
    gb_balance     REAL NOT NULL DEFAULT 0,
    total_charged  REAL NOT NULL DEFAULT 0,
    total_used     REAL NOT NULL DEFAULT 0,
    is_active      INTEGER NOT NULL DEFAULT 1,
    price_per_gb   INTEGER,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
);

CREATE TABLE IF NOT EXISTS rep_charges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id     INTEGER NOT NULL,
    gb_amount       REAL NOT NULL,
    gb_cashback     REAL NOT NULL DEFAULT 0,
    price_per_gb    INTEGER NOT NULL,
    total_price     INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending_receipt',
    receipt_file_id TEXT,
    admin_note      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at     TEXT,
    FOREIGN KEY (telegram_id) REFERENCES sales_reps(telegram_id)
);

CREATE TABLE IF NOT EXISTS rep_configs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    rep_telegram_id  INTEGER NOT NULL,
    config_name      TEXT NOT NULL,
    gb_allocated     REAL NOT NULL,
    duration_days    INTEGER NOT NULL,
    marzban_username TEXT,
    subscription_url TEXT,
    status           TEXT NOT NULL DEFAULT 'active',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (rep_telegram_id) REFERENCES sales_reps(telegram_id)
);

CREATE INDEX IF NOT EXISTS idx_rep_charges_status      ON rep_charges(status);
CREATE INDEX IF NOT EXISTS idx_rep_charges_telegram_id ON rep_charges(telegram_id);
CREATE INDEX IF NOT EXISTS idx_rep_configs_rep_id      ON rep_configs(rep_telegram_id);
"""

_SQLITE_MIGRATIONS = [
    ("ALTER TABLE sales_reps ADD COLUMN price_per_gb INTEGER",                      "sales_reps.price_per_gb"),
    ("ALTER TABLE orders ADD COLUMN config_name TEXT",                              "orders.config_name"),
    ("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'fa'",            "users.language"),
    ("ALTER TABLE plans ADD COLUMN user_limit INTEGER NOT NULL DEFAULT 1",          "plans.user_limit"),
    ("ALTER TABLE plans ADD COLUMN data_limit_gb_new INTEGER",                      "plans.data_limit_gb_new"),
    ("ALTER TABLE users ADD COLUMN phone_number TEXT",                              "users.phone_number"),
    ("ALTER TABLE orders ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'card'",   "orders.payment_method"),
    ("ALTER TABLE orders ADD COLUMN nowpayments_id TEXT",                           "orders.nowpayments_id"),
]


class SqliteConn(DbConn):
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def fetchone(self, query: str, params: tuple = ()) -> Any | None:
        async with self._conn.execute(query, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, query: str, params: tuple = ()) -> list[Any]:
        async with self._conn.execute(query, params) as cur:
            return await cur.fetchall()

    async def execute(self, query: str, params: tuple = ()) -> None:
        await self._conn.execute(query, params)

    async def execute_returning_id(self, query: str, params: tuple = ()) -> int:
        async with self._conn.execute(query, params) as cur:
            row_id = cur.lastrowid
        await self._conn.commit()
        return row_id  # type: ignore[return-value]

    async def commit(self) -> None:
        await self._conn.commit()


# ── PostgreSQL backend ─────────────────────────────────────────────────────────

# Timestamps are stored as TEXT (same format as SQLite: 'YYYY-MM-DD HH24:MI:SS')
# so that handlers calling datetime.fromisoformat() work identically on both backends.
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
    """
    CREATE TABLE IF NOT EXISTS sales_reps (
        telegram_id    BIGINT PRIMARY KEY REFERENCES users(telegram_id),
        gb_balance     REAL NOT NULL DEFAULT 0,
        total_charged  REAL NOT NULL DEFAULT 0,
        total_used     REAL NOT NULL DEFAULT 0,
        is_active      INTEGER NOT NULL DEFAULT 1,
        price_per_gb   INTEGER,
        created_at     TEXT NOT NULL
                           DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rep_charges (
        id              SERIAL PRIMARY KEY,
        telegram_id     BIGINT NOT NULL REFERENCES sales_reps(telegram_id),
        gb_amount       REAL NOT NULL,
        gb_cashback     REAL NOT NULL DEFAULT 0,
        price_per_gb    INTEGER NOT NULL,
        total_price     INTEGER NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending_receipt',
        receipt_file_id TEXT,
        admin_note      TEXT,
        created_at      TEXT NOT NULL
                            DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
        reviewed_at     TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rep_configs (
        id               SERIAL PRIMARY KEY,
        rep_telegram_id  BIGINT NOT NULL REFERENCES sales_reps(telegram_id),
        config_name      TEXT NOT NULL,
        gb_allocated     REAL NOT NULL,
        duration_days    INTEGER NOT NULL,
        marzban_username TEXT,
        subscription_url TEXT,
        status           TEXT NOT NULL DEFAULT 'active',
        created_at       TEXT NOT NULL
                             DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rep_charges_status      ON rep_charges(status)",
    "CREATE INDEX IF NOT EXISTS idx_rep_charges_telegram_id ON rep_charges(telegram_id)",
    "CREATE INDEX IF NOT EXISTS idx_rep_configs_rep_id      ON rep_configs(rep_telegram_id)",
]

_QUESTION_MARK = re.compile(r"\?")
_pg_pool: Any = None  # asyncpg.Pool, populated by init_db()


def _to_pg(query: str) -> str:
    """Convert SQLite ? placeholders to PostgreSQL $1, $2, ..."""
    n = 0

    def _next(_m: re.Match) -> str:
        nonlocal n
        n += 1
        return f"${n}"

    return _QUESTION_MARK.sub(_next, query)


class PgConn(DbConn):
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def fetchone(self, query: str, params: tuple = ()) -> Any | None:
        return await self._conn.fetchrow(_to_pg(query), *params)

    async def fetchall(self, query: str, params: tuple = ()) -> list[Any]:
        return await self._conn.fetch(_to_pg(query), *params)

    async def execute(self, query: str, params: tuple = ()) -> None:
        await self._conn.execute(_to_pg(query), *params)

    async def execute_returning_id(self, query: str, params: tuple = ()) -> int:
        row = await self._conn.fetchrow(_to_pg(query) + " RETURNING id", *params)
        return row["id"]

    async def commit(self) -> None:
        pass  # asyncpg uses autocommit outside of explicit transactions


# ── Context manager ────────────────────────────────────────────────────────────

@asynccontextmanager
async def get_db() -> AsyncIterator[DbConn]:
    if settings.db_backend == "postgres":
        if _pg_pool is None:
            raise RuntimeError("PostgreSQL pool is not initialised; call init_db() first")
        async with _pg_pool.acquire() as conn:
            yield PgConn(conn)
    else:
        import aiosqlite
        async with aiosqlite.connect(settings.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys = ON")
            yield SqliteConn(db)


# ── Init ───────────────────────────────────────────────────────────────────────

async def init_db() -> None:
    global _pg_pool

    if settings.db_backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL must be set when DB_BACKEND=postgres")
        import asyncpg
        _pg_pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
        async with _pg_pool.acquire() as conn:
            for stmt in _PG_DDL:
                await conn.execute(stmt)
            # Idempotent column additions for existing deployments
            await conn.execute(
                "ALTER TABLE sales_reps ADD COLUMN IF NOT EXISTS price_per_gb INTEGER"
            )
        logger.info("PostgreSQL database initialised")
        return

    # SQLite path — keep legacy migration logic intact
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    import aiosqlite
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(_SQLITE_DDL)
        for migration_sql, description in _SQLITE_MIGRATIONS:
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
    logger.info("SQLite database initialised at %s", settings.db_path)


async def close_db() -> None:
    """Close the PostgreSQL connection pool on shutdown."""
    if settings.db_backend == "postgres" and _pg_pool is not None:
        await _pg_pool.close()
