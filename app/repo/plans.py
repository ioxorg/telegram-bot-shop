from __future__ import annotations

from typing import Any

from app.db import DbConn


async def get_active_plans(db: DbConn) -> list[Any]:
    return await db.fetchall(
        "SELECT * FROM plans WHERE is_active = 1 ORDER BY price"
    )


async def get_all_plans(db: DbConn) -> list[Any]:
    return await db.fetchall(
        "SELECT * FROM plans ORDER BY is_active DESC, price"
    )


async def get_plan(db: DbConn, plan_id: int) -> Any | None:
    return await db.fetchone(
        "SELECT * FROM plans WHERE id = ? AND is_active = 1", (plan_id,)
    )


async def get_plan_any(db: DbConn, plan_id: int) -> Any | None:
    return await db.fetchone("SELECT * FROM plans WHERE id = ?", (plan_id,))


async def create_plan(
    db: DbConn,
    data_limit_gb: int,
    duration_days: int,
    user_limit: int,
    price: int,
) -> int:
    return await db.execute_returning_id(
        "INSERT INTO plans (data_limit_gb, duration_days, user_limit, price) VALUES (?, ?, ?, ?)",
        (data_limit_gb, duration_days, user_limit, price),
    )


async def update_plan(
    db: DbConn,
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


async def toggle_plan(db: DbConn, plan_id: int) -> bool:
    row = await db.fetchone("SELECT is_active FROM plans WHERE id = ?", (plan_id,))
    if not row:
        return False
    new_state = 0 if row["is_active"] else 1
    await db.execute("UPDATE plans SET is_active = ? WHERE id = ?", (new_state, plan_id))
    await db.commit()
    return bool(new_state)


async def delete_plan(db: DbConn, plan_id: int) -> None:
    await db.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
    await db.commit()
