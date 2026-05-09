from __future__ import annotations

import aiosqlite


async def get_active_plans(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    async with db.execute(
        "SELECT * FROM plans WHERE is_active = 1 ORDER BY price"
    ) as cur:
        return await cur.fetchall()


async def get_all_plans(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    async with db.execute("SELECT * FROM plans ORDER BY is_active DESC, price") as cur:
        return await cur.fetchall()


async def get_plan(db: aiosqlite.Connection, plan_id: int) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT * FROM plans WHERE id = ? AND is_active = 1", (plan_id,)
    ) as cur:
        return await cur.fetchone()


async def get_plan_any(db: aiosqlite.Connection, plan_id: int) -> aiosqlite.Row | None:
    async with db.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)) as cur:
        return await cur.fetchone()


async def create_plan(
    db: aiosqlite.Connection,
    data_limit_gb: int,
    duration_days: int,
    user_limit: int,
    price: int,
) -> int:
    async with db.execute(
        "INSERT INTO plans (data_limit_gb, duration_days, user_limit, price) VALUES (?, ?, ?, ?)",
        (data_limit_gb, duration_days, user_limit, price),
    ) as cur:
        plan_id = cur.lastrowid
    await db.commit()
    return plan_id


async def update_plan(
    db: aiosqlite.Connection,
    plan_id: int,
    data_limit_gb: int,
    duration_days: int,
    user_limit: int,
    price: int,
) -> None:
    await db.execute(
        "UPDATE plans SET data_limit_gb=?, duration_days=?, user_limit=?, price=? WHERE id=?",
        (data_limit_gb, duration_days, user_limit, price, plan_id),
    )
    await db.commit()


async def toggle_plan(db: aiosqlite.Connection, plan_id: int) -> bool:
    async with db.execute("SELECT is_active FROM plans WHERE id = ?", (plan_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return False
    new_state = 0 if row["is_active"] else 1
    await db.execute("UPDATE plans SET is_active = ? WHERE id = ?", (new_state, plan_id))
    await db.commit()
    return bool(new_state)


async def delete_plan(db: aiosqlite.Connection, plan_id: int) -> None:
    await db.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
    await db.commit()
