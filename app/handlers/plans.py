from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db import get_db
from app.i18n import t
from app.keyboards import plan_detail, plan_list
from app.repo.bot_settings import get_active_payment_methods, get_payment_settings
from app.repo.plans import get_active_plans, get_plan

router = Router()
logger = logging.getLogger(__name__)


def _data_label(gb: int) -> str:
    return "∞" if gb == 0 else f"{gb} GB"


def _user_label(n: int) -> str:
    return "∞ Users" if n == 0 else f"{n} User"


def _plan_title(plan) -> str:
    return f"{_data_label(plan['data_limit_gb'])} – {plan['duration_days']} Days – {_user_label(plan['user_limit'])}"


async def _send_plan_list(plans: list, message: Message, lang: str, currency: str) -> None:
    await message.answer(t("choose_plan", lang), reply_markup=plan_list(plans, lang, currency))


@router.message(Command("buy"))
async def cmd_buy(message: Message, lang: str) -> None:
    async with get_db() as db:
        methods = await get_active_payment_methods(db)
        if not any(methods.values()):
            await message.answer(t("payments_disabled", lang))
            return
        plans = await get_active_plans(db)
        ps = await get_payment_settings(db)
    if not plans:
        await message.answer(t("no_plans", lang))
        return
    await _send_plan_list(plans, message, lang, ps["currency_label"])


@router.callback_query(lambda c: c.data == "menu:buy")
async def cb_buy(callback: CallbackQuery, lang: str) -> None:
    async with get_db() as db:
        methods = await get_active_payment_methods(db)
        if not any(methods.values()):
            await callback.answer(t("payments_disabled", lang), show_alert=True)
            return
        plans = await get_active_plans(db)
        ps = await get_payment_settings(db)
    if not plans:
        await callback.answer(t("no_plans", lang), show_alert=True)
        return
    await callback.message.edit_text(
        t("choose_plan", lang), reply_markup=plan_list(plans, lang, ps["currency_label"])
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("plan:select:"))
async def cb_plan_select(callback: CallbackQuery, lang: str) -> None:
    plan_id = int(callback.data.split(":")[2])
    async with get_db() as db:
        methods = await get_active_payment_methods(db)
        if not any(methods.values()):
            await callback.answer(t("payments_disabled", lang), show_alert=True)
            return
        plan = await get_plan(db, plan_id)
        ps = await get_payment_settings(db)
    if not plan:
        await callback.answer(t("order_not_found", lang), show_alert=True)
        return

    text = t(
        "plan_detail", lang,
        title=_plan_title(plan),
        days=plan["duration_days"],
        data=_data_label(plan["data_limit_gb"]),
        users=_user_label(plan["user_limit"]),
        price=f"{plan['price']:,}",
        currency=ps["currency_label"],
    )
    await callback.message.edit_text(
        text, parse_mode="HTML", reply_markup=plan_detail(plan_id, lang)
    )
    await callback.answer()
    logger.info("User %d viewing plan %d", callback.from_user.id, plan_id)
