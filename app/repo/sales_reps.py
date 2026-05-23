from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db import DbConn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ── Rep accounts ──────────────────────────────────────────────────────────────

async def get_rep(db: DbConn, telegram_id: int) -> Any | None:
    return await db.fetchone(
        "SELECT * FROM sales_reps WHERE telegram_id = ?", (telegram_id,)
    )


async def create_rep(db: DbConn, telegram_id: int) -> None:
    await db.execute(
        "INSERT INTO sales_reps (telegram_id, created_at) VALUES (?, ?) ON CONFLICT DO NOTHING",
        (telegram_id, _now()),
    )
    await db.commit()


async def get_all_reps(db: DbConn) -> list[Any]:
    return await db.fetchall(
        """
        SELECT r.*, u.username, u.first_name
        FROM sales_reps r
        JOIN users u ON u.telegram_id = r.telegram_id
        ORDER BY r.created_at DESC
        """
    )


async def set_rep_price_per_gb(db: DbConn, telegram_id: int, price: int | None) -> None:
    """Set a custom price per GB for this rep, or None to revert to the global rate."""
    await db.execute(
        "UPDATE sales_reps SET price_per_gb = ? WHERE telegram_id = ?",
        (price, telegram_id),
    )
    await db.commit()


async def toggle_rep_active(db: DbConn, telegram_id: int) -> bool:
    rep = await get_rep(db, telegram_id)
    if rep is None:
        return False
    new_val = 0 if rep["is_active"] else 1
    await db.execute(
        "UPDATE sales_reps SET is_active = ? WHERE telegram_id = ?",
        (new_val, telegram_id),
    )
    await db.commit()
    return bool(new_val)


async def credit_gb(db: DbConn, telegram_id: int, gb_amount: float, gb_cashback: float) -> None:
    total = gb_amount + gb_cashback
    await db.execute(
        """
        UPDATE sales_reps
        SET gb_balance    = gb_balance    + ?,
            total_charged = total_charged + ?
        WHERE telegram_id = ?
        """,
        (total, gb_amount, telegram_id),
    )
    await db.commit()


async def deduct_gb(db: DbConn, telegram_id: int, gb_amount: float) -> None:
    await db.execute(
        """
        UPDATE sales_reps
        SET gb_balance  = gb_balance  - ?,
            total_used  = total_used  + ?
        WHERE telegram_id = ?
        """,
        (gb_amount, gb_amount, telegram_id),
    )
    await db.commit()


# ── Rep charges (top-up requests) ────────────────────────────────────────────

async def create_charge(
    db: DbConn,
    telegram_id: int,
    gb_amount: float,
    price_per_gb: int,
    total_price: int,
) -> int:
    return await db.execute_returning_id(
        """
        INSERT INTO rep_charges (telegram_id, gb_amount, price_per_gb, total_price, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (telegram_id, gb_amount, price_per_gb, total_price, _now()),
    )


async def set_charge_receipt(db: DbConn, charge_id: int, file_id: str) -> None:
    await db.execute(
        """
        UPDATE rep_charges
        SET receipt_file_id = ?, status = 'pending_review'
        WHERE id = ?
        """,
        (file_id, charge_id),
    )
    await db.commit()


async def get_charge(db: DbConn, charge_id: int) -> Any | None:
    return await db.fetchone(
        """
        SELECT c.*, u.username, u.first_name
        FROM rep_charges c
        JOIN users u ON u.telegram_id = c.telegram_id
        WHERE c.id = ?
        """,
        (charge_id,),
    )


async def get_pending_charges(db: DbConn) -> list[Any]:
    return await db.fetchall(
        """
        SELECT c.*, u.username, u.first_name
        FROM rep_charges c
        JOIN users u ON u.telegram_id = c.telegram_id
        WHERE c.status = 'pending_review'
        ORDER BY c.created_at
        """
    )


async def approve_charge(db: DbConn, charge_id: int, gb_cashback: float) -> None:
    await db.execute(
        """
        UPDATE rep_charges
        SET status = 'approved', gb_cashback = ?, reviewed_at = ?
        WHERE id = ?
        """,
        (gb_cashback, _now(), charge_id),
    )
    await db.commit()


async def reject_charge(db: DbConn, charge_id: int, reason: str) -> None:
    await db.execute(
        """
        UPDATE rep_charges
        SET status = 'rejected', admin_note = ?, reviewed_at = ?
        WHERE id = ?
        """,
        (reason, _now(), charge_id),
    )
    await db.commit()


async def get_rep_charges(db: DbConn, telegram_id: int, limit: int = 10) -> list[Any]:
    return await db.fetchall(
        """
        SELECT * FROM rep_charges
        WHERE telegram_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (telegram_id, limit),
    )


# ── Rep configs ───────────────────────────────────────────────────────────────

async def create_rep_config(
    db: DbConn,
    rep_telegram_id: int,
    config_name: str,
    gb_allocated: float,
    duration_days: int,
    marzban_username: str,
    subscription_url: str,
) -> int:
    return await db.execute_returning_id(
        """
        INSERT INTO rep_configs (rep_telegram_id, config_name, gb_allocated, duration_days,
                                  marzban_username, subscription_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (rep_telegram_id, config_name, gb_allocated, duration_days,
         marzban_username, subscription_url, _now()),
    )


async def get_rep_configs(db: DbConn, rep_telegram_id: int, limit: int = 15) -> list[Any]:
    return await db.fetchall(
        """
        SELECT * FROM rep_configs
        WHERE rep_telegram_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (rep_telegram_id, limit),
    )
