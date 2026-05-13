from __future__ import annotations

import aiosqlite


async def create_order(
    db: aiosqlite.Connection,
    telegram_id: int,
    plan_id: int,
    price: int,
    payment_method: str = "card",
) -> int:
    async with db.execute(
        "INSERT INTO orders (telegram_id, plan_id, price, payment_method) VALUES (?, ?, ?, ?)",
        (telegram_id, plan_id, price, payment_method),
    ) as cur:
        await db.commit()
        return cur.lastrowid  # type: ignore[return-value]


async def set_config_name(db: aiosqlite.Connection, order_id: int, config_name: str) -> None:
    await db.execute(
        "UPDATE orders SET config_name = ? WHERE id = ?",
        (config_name, order_id),
    )
    await db.commit()


async def set_nowpayments_id(db: aiosqlite.Connection, order_id: int, payment_id: str) -> None:
    await db.execute(
        "UPDATE orders SET nowpayments_id = ? WHERE id = ?",
        (payment_id, order_id),
    )
    await db.commit()


_PLAN_TITLE_SQL = """
    CASE WHEN p.data_limit_gb = 0 THEN '∞ GB' ELSE CAST(p.data_limit_gb AS TEXT) || ' GB' END
    || ' – ' || CAST(p.duration_days AS TEXT) || ' Days'
    || ' – ' || CASE WHEN p.user_limit = 0 THEN '∞ Users' ELSE CAST(p.user_limit AS TEXT) || ' User' END
"""


async def get_order(db: aiosqlite.Connection, order_id: int) -> aiosqlite.Row | None:
    async with db.execute(
        f"""
        SELECT o.*, p.duration_days, p.data_limit_gb, p.user_limit,
               ({_PLAN_TITLE_SQL}) AS title
        FROM orders o
        JOIN plans p ON p.id = o.plan_id
        WHERE o.id = ?
        """,
        (order_id,),
    ) as cur:
        return await cur.fetchone()


async def set_receipt(
    db: aiosqlite.Connection, order_id: int, file_id: str, config_name: str
) -> None:
    await db.execute(
        """
        UPDATE orders
        SET receipt_file_id = ?, config_name = ?, status = 'pending_review'
        WHERE id = ?
        """,
        (file_id, config_name, order_id),
    )
    await db.commit()


async def approve_order(
    db: aiosqlite.Connection,
    order_id: int,
    marzban_username: str,
    subscription_url: str,
) -> None:
    await db.execute(
        """
        UPDATE orders
        SET status = 'approved',
            marzban_username = ?,
            subscription_url = ?,
            reviewed_at = datetime('now')
        WHERE id = ?
        """,
        (marzban_username, subscription_url, order_id),
    )
    await db.commit()


async def reject_order(
    db: aiosqlite.Connection, order_id: int, reason: str
) -> None:
    await db.execute(
        """
        UPDATE orders
        SET status = 'rejected',
            admin_note = ?,
            reviewed_at = datetime('now')
        WHERE id = ?
        """,
        (reason, order_id),
    )
    await db.commit()


async def fail_order(
    db: aiosqlite.Connection, order_id: int, note: str
) -> None:
    await db.execute(
        """
        UPDATE orders
        SET status = 'failed',
            admin_note = ?,
            reviewed_at = datetime('now')
        WHERE id = ?
        """,
        (note, order_id),
    )
    await db.commit()


async def cancel_order(db: aiosqlite.Connection, order_id: int) -> None:
    await db.execute(
        """
        UPDATE orders
        SET status = 'rejected', admin_note = 'user cancelled'
        WHERE id = ? AND status = 'pending_receipt'
        """,
        (order_id,),
    )
    await db.commit()


async def get_approved_orders(
    db: aiosqlite.Connection, telegram_id: int
) -> list[aiosqlite.Row]:
    async with db.execute(
        f"""
        SELECT o.*, p.duration_days, p.data_limit_gb, p.user_limit,
               ({_PLAN_TITLE_SQL}) AS title
        FROM orders o
        JOIN plans p ON p.id = o.plan_id
        WHERE o.telegram_id = ? AND o.status = 'approved'
        ORDER BY o.reviewed_at DESC
        """,
        (telegram_id,),
    ) as cur:
        return await cur.fetchall()


async def get_pending_orders(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    async with db.execute(
        f"""
        SELECT o.*, ({_PLAN_TITLE_SQL}) AS title, u.username, u.first_name
        FROM orders o
        JOIN plans p ON p.id = o.plan_id
        JOIN users u ON u.telegram_id = o.telegram_id
        WHERE o.status = 'pending_review'
        ORDER BY o.created_at
        """,
    ) as cur:
        return await cur.fetchall()


async def get_failed_orders(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    async with db.execute(
        f"""
        SELECT o.*, ({_PLAN_TITLE_SQL}) AS title, u.username, u.first_name
        FROM orders o
        JOIN plans p ON p.id = o.plan_id
        JOIN users u ON u.telegram_id = o.telegram_id
        WHERE o.status = 'failed'
        ORDER BY o.reviewed_at DESC
        LIMIT 50
        """,
    ) as cur:
        return await cur.fetchall()


async def count_approved(db: aiosqlite.Connection) -> int:
    async with db.execute(
        "SELECT COUNT(*) FROM orders WHERE status = 'approved'"
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else 0


async def total_revenue(db: aiosqlite.Connection) -> int:
    async with db.execute(
        "SELECT COALESCE(SUM(price), 0) FROM orders WHERE status = 'approved'"
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else 0
