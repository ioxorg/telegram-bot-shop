from __future__ import annotations

from typing import Any

from app.db import DbConn

_DEFAULTS: dict[str, str] = {
    "card_number": "",
    "bank_name": "",
    "card_holder_name": "",
    "currency_label": "تومان",
    "card_payment_enabled": "1",
    "stars_payment_enabled": "0",
    "stars_toman_per_star": "1000",
    "nowpayments_enabled": "0",
    "usd_toman_rate": "600000",
    "phone_verification_enabled": "1",
    "force_join_enabled": "0",
    "force_join_channel": "",
    # ── Sales rep settings ────────────────────────────────────────────────────
    "rep_price_per_gb": "5000",
    "rep_config_duration_days": "30",
    "rep_cashback_threshold_gb": "40",
    "rep_cashback_percent": "5",
    "rep_min_config_gb": "5",
    "rep_max_config_gb": "30",
    # Rep-specific card payment details (separate from customer card)
    "rep_card_number": "",
    "rep_bank_name": "",
    "rep_card_holder_name": "",
}

_ALL_KEYS = ", ".join(f"'{k}'" for k in _DEFAULTS)


async def get_setting(db: DbConn, key: str) -> str:
    row = await db.fetchone(
        "SELECT value FROM bot_settings WHERE key = ?", (key,)
    )
    return row["value"] if row else _DEFAULTS.get(key, "")


async def set_setting(db: DbConn, key: str, value: str) -> None:
    await db.execute(
        """
        INSERT INTO bot_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    await db.commit()


async def get_payment_settings(db: DbConn) -> dict[str, str]:
    rows = await db.fetchall(
        f"SELECT key, value FROM bot_settings WHERE key IN ({_ALL_KEYS})"
    )
    result = dict(_DEFAULTS)
    for row in rows:
        result[row["key"]] = row["value"]
    return result


async def get_active_payment_methods(
    db: DbConn,
    nowpayments_api_key: str = "",
) -> dict[str, bool]:
    ps = await get_payment_settings(db)
    return {
        "card": ps["card_payment_enabled"] == "1",
        "stars": ps["stars_payment_enabled"] == "1",
        "nowpayments": ps["nowpayments_enabled"] == "1" and bool(nowpayments_api_key),
    }


async def _toggle(db: DbConn, key: str) -> bool:
    current = await get_setting(db, key)
    new_value = "0" if current == "1" else "1"
    await set_setting(db, key, new_value)
    return new_value == "1"


async def toggle_payment_enabled(db: DbConn) -> bool:
    return await _toggle(db, "card_payment_enabled")


async def toggle_stars_payment(db: DbConn) -> bool:
    return await _toggle(db, "stars_payment_enabled")


async def toggle_nowpayments(db: DbConn) -> bool:
    return await _toggle(db, "nowpayments_enabled")


async def toggle_phone_verification(db: DbConn) -> bool:
    return await _toggle(db, "phone_verification_enabled")


async def toggle_force_join(db: DbConn) -> bool:
    return await _toggle(db, "force_join_enabled")


async def seed_payment_settings(
    db: DbConn,
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
            "INSERT INTO bot_settings (key, value) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (key, value),
        )
    await db.commit()
