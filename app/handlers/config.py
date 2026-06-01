from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import CallbackQuery

from app.db import get_db
from app.i18n import t
from app.panel import PanelError, fetch_individual_links
from app.repo.orders import get_order

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(lambda c: c.data and c.data.startswith("sub:configs:"))
async def cb_get_configs(callback: CallbackQuery, lang: str) -> None:
    order_id = int(callback.data.split(":")[2])

    async with get_db() as db:
        order = await get_order(db, order_id)

    if not order or order["telegram_id"] != callback.from_user.id:
        await callback.answer(t("order_not_found", lang), show_alert=True)
        return

    if order["status"] != "approved" or not order["marzban_username"]:
        await callback.answer(t("sub_not_active", lang), show_alert=True)
        return

    config_name: str = order["config_name"] or "VPN"
    await callback.answer()
    wait_msg = await callback.message.answer(t("fetching_configs", lang))

    try:
        links = await fetch_individual_links(order["marzban_username"], config_name)
    except PanelError as exc:
        logger.error("Failed to fetch configs for order %d: %s", order_id, exc)
        await wait_msg.delete()
        await callback.message.answer(t("configs_error", lang))
        return

    await wait_msg.delete()
    await callback.message.answer(
        t("configs_ready", lang, count=len(links), name=config_name),
        parse_mode="HTML",
    )
    for link in links:
        await callback.message.answer(f"<code>{link}</code>", parse_mode="HTML")

    logger.info("Sent %d configs (name=%r) for order %d to user %d",
                len(links), config_name, order_id, callback.from_user.id)
