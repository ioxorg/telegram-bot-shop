from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.db import get_db
from app.i18n import t
from app.repo.orders import get_approved_orders, get_order

router = Router()
logger = logging.getLogger(__name__)


def _expiry(reviewed_at: str, duration_days: int) -> str:
    try:
        dt = datetime.fromisoformat(reviewed_at) + timedelta(days=duration_days)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return "Unknown"


def _build_subs_content(orders: list, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    if not orders:
        return (
            t("no_subs", lang),
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t("btn_back", lang), callback_data="menu:back")]
            ]),
        )
    rows = [
        [InlineKeyboardButton(
            text=f"📱 {order['config_name'] or order['title']}",
            callback_data=f"sub:detail:{order['id']}",
        )]
        for order in orders
    ]
    rows.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data="menu:back")])
    return t("subs_list", lang), InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("my_subs"))
async def cmd_my_subs(message: Message, lang: str) -> None:
    async with get_db() as db:
        orders = await get_approved_orders(db, message.from_user.id)
    text, kb = _build_subs_content(orders, lang)
    await message.answer(text, reply_markup=kb)


@router.callback_query(lambda c: c.data == "menu:my_subs")
async def cb_my_subs(callback: CallbackQuery, lang: str) -> None:
    async with get_db() as db:
        orders = await get_approved_orders(db, callback.from_user.id)
    text, kb = _build_subs_content(orders, lang)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("sub:detail:"))
async def cb_sub_detail(callback: CallbackQuery, lang: str) -> None:
    order_id = int(callback.data.split(":")[2])
    async with get_db() as db:
        order = await get_order(db, order_id)

    if not order or order["telegram_id"] != callback.from_user.id:
        await callback.answer(t("order_not_found", lang), show_alert=True)
        return

    expiry = _expiry(order["reviewed_at"], order["duration_days"])
    label = order["config_name"] or order["title"]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t("btn_sub_link", lang), callback_data=f"sub:show:{order_id}"),
            InlineKeyboardButton(text=t("btn_get_configs", lang), callback_data=f"sub:configs:{order_id}"),
        ],
        [InlineKeyboardButton(text=t("btn_my_subs_back", lang), callback_data="menu:my_subs")],
    ])
    await callback.message.edit_text(
        t("sub_detail", lang, name=label, plan=order["title"], expiry=expiry),
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("sub:show:"))
async def cb_show_link(callback: CallbackQuery, lang: str) -> None:
    order_id = int(callback.data.split(":")[2])
    async with get_db() as db:
        order = await get_order(db, order_id)

    if not order or order["telegram_id"] != callback.from_user.id:
        await callback.answer(t("order_not_found", lang), show_alert=True)
        return

    await callback.message.answer(
        t("sub_link_msg", lang, url=order["subscription_url"]),
        parse_mode="HTML",
    )
    await callback.answer()
