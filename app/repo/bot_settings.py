from __future__ import annotations

import aiosqlite

_DEFAULTS: dict[str, str] = {
    "card_number": "",
    "bank_name": "",
    "card_holder_name": "",
    "currency_label": "تومان",
    "card_payment_enabled": "1",
    "stars_payment_enabled": "0",
    "stars_toman_per_star": "1000",
    "ton_payment_enabled": "0",
    "ton_wallet_address": "",
    "ton_toman_per_ton": "50000000",
}

_ALL_KEYS = ", ".join(f"'{k}'" for k in _DEFAULTS)


async def get_setting(db: aiosqlite.Connection, key: str) -> str:
    async with db.execute(
        "SELECT value FROM bot_settings WHERE key = ?", (key,)
    ) as cur:
        row = await cur.fetchone()
    return row["value"] if row else _DEFAULTS.get(key, "")


async def set_setting(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute(
        """
        INSERT INTO bot_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    await db.commit()


async def get_payment_settings(db: aiosqlite.Connection) -> dict[str, str]:
    async with db.execute(
        f"SELECT key, value FROM bot_settings WHERE key IN ({_ALL_KEYS})"
    ) as cur:
        rows = await cur.fetchall()
    result = dict(_DEFAULTS)
    for row in rows:
        result[row["key"]] = row["value"]
    return result


async def get_active_payment_methods(db: aiosqlite.Connection) -> dict[str, bool]:
    ps = await get_payment_settings(db)
    return {
        "card": ps["card_payment_enabled"] == "1",
        "stars": ps["stars_payment_enabled"] == "1",
        "ton": ps["ton_payment_enabled"] == "1",
    }


async def _toggle(db: aiosqlite.Connection, key: str) -> bool:
    current = await get_setting(db, key)
    new_value = "0" if current == "1" else "1"
    await set_setting(db, key, new_value)
    return new_value == "1"


async def toggle_payment_enabled(db: aiosqlite.Connection) -> bool:
    return await _toggle(db, "card_payment_enabled")


async def toggle_stars_payment(db: aiosqlite.Connection) -> bool:
    return await _toggle(db, "stars_payment_enabled")


async def toggle_ton_payment(db: aiosqlite.Connection) -> bool:
    return await _toggle(db, "ton_payment_enabled")


async def seed_payment_settings(
    db: aiosqlite.Connection,
    card_number: str,
    card_holder_name: str,
    currency_label: str,
) -> None:
    """Seed from env vars on first run only — skips keys that already exist."""
    for key, value in [
        ("card_number", card_number),
        ("card_holder_name", card_holder_name),
        ("currency_label", currency_label),
    ]:
        await db.execute(
            "INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    await db.commit()
