from __future__ import annotations

import aiosqlite
from aiogram.types import User as TgUser


async def upsert_user(db: aiosqlite.Connection, user: TgUser) -> bool:
    """Returns True if this is the user's first visit."""
    async with db.execute(
        "SELECT 1 FROM users WHERE telegram_id = ?", (user.id,)
    ) as cur:
        is_new = await cur.fetchone() is None

    await db.execute(
        """
        INSERT INTO users (telegram_id, username, first_name, language_code)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            username      = excluded.username,
            first_name    = excluded.first_name,
            language_code = excluded.language_code
        """,
        (user.id, user.username, user.first_name, user.language_code),
    )
    await db.commit()
    return is_new


async def get_user_language(db: aiosqlite.Connection, telegram_id: int) -> str:
    async with db.execute(
        "SELECT language FROM users WHERE telegram_id = ?", (telegram_id,)
    ) as cur:
        row = await cur.fetchone()
    return row["language"] if row else "fa"


async def set_user_language(
    db: aiosqlite.Connection, telegram_id: int, lang: str
) -> None:
    await db.execute(
        "UPDATE users SET language = ? WHERE telegram_id = ?",
        (lang, telegram_id),
    )
    await db.commit()


async def get_phone_number(db: aiosqlite.Connection, telegram_id: int) -> str | None:
    async with db.execute(
        "SELECT phone_number FROM users WHERE telegram_id = ?", (telegram_id,)
    ) as cur:
        row = await cur.fetchone()
    return row["phone_number"] if row else None


async def set_phone_number(db: aiosqlite.Connection, telegram_id: int, phone: str) -> None:
    await db.execute(
        "UPDATE users SET phone_number = ? WHERE telegram_id = ?", (phone, telegram_id)
    )
    await db.commit()


async def count_users(db: aiosqlite.Connection) -> int:
    async with db.execute("SELECT COUNT(*) FROM users") as cur:
        row = await cur.fetchone()
        return row[0] if row else 0
