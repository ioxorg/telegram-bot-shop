from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from app.db import get_db
from app.i18n import t
from app.keyboards import admin_review, payment_method_keyboard
from app.marzban import MarzbanError, check_username_available, create_subscription, validate_config_name
from app.repo.bot_settings import get_active_payment_methods, get_setting
from app.repo.orders import (
    approve_order,
    cancel_order,
    create_order,
    fail_order,
    get_order,
    set_config_name,
    set_receipt,
)
from app.repo.plans import get_plan
from app.repo.users import get_user_language
from app.states import PurchaseStates
from configs.configs import settings

router = Router()
logger = logging.getLogger(__name__)

_NAME_MAX = 32


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stars_for_price(price: int, toman_per_star: int) -> int:
    return max(1, math.ceil(price / toman_per_star))


def _ton_for_price(price: int, toman_per_ton: int) -> str:
    amount = price / toman_per_ton
    # Format with up to 6 significant decimal places, strip trailing zeros
    return f"{amount:.6f}".rstrip("0").rstrip(".")


# ── Plan paid — payment method selection ──────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("plan:paid:"))
async def cb_plan_paid(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    plan_id = int(callback.data.split(":")[2])

    async with get_db() as db:
        methods = await get_active_payment_methods(db)
        plan = await get_plan(db, plan_id)

    if not plan:
        await callback.answer(t("order_not_found", lang), show_alert=True)
        return

    enabled = {k: v for k, v in methods.items() if v}
    if not enabled:
        await callback.answer(t("payments_disabled", lang), show_alert=True)
        return

    if len(enabled) == 1:
        method = next(iter(enabled))
        await _start_method_flow(callback, state, lang, plan_id, method)
        return

    await callback.message.edit_text(
        t("choose_payment_method", lang),
        reply_markup=payment_method_keyboard(plan_id, lang, methods),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("plan:method:"))
async def cb_plan_method(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    parts = callback.data.split(":")  # plan:method:{method}:{plan_id}
    method, plan_id = parts[2], int(parts[3])

    # Guard: re-check the method is still enabled
    async with get_db() as db:
        methods = await get_active_payment_methods(db)
    if not methods.get(method):
        await callback.answer(t("payments_disabled", lang), show_alert=True)
        return

    await _start_method_flow(callback, state, lang, plan_id, method)


async def _start_method_flow(
    callback: CallbackQuery,
    state: FSMContext,
    lang: str,
    plan_id: int,
    method: str,
) -> None:
    async with get_db() as db:
        plan = await get_plan(db, plan_id)
        if not plan:
            await callback.answer(t("order_not_found", lang), show_alert=True)
            return
        order_id = await create_order(
            db, callback.from_user.id, plan_id, plan["price"], payment_method=method
        )
        currency = await get_setting(db, "currency_label")

    from app.handlers.plans import _plan_title
    plan_title = _plan_title(plan)

    state_data: dict = {
        "order_id": order_id,
        "price": plan["price"],
        "plan_title": plan_title,
        "plan_id": plan_id,
        "lang": lang,
        "payment_method": method,
        "currency": currency,
    }

    async with get_db() as db:
        if method == "card":
            state_data["card_number"] = await get_setting(db, "card_number")
            state_data["bank_name"] = await get_setting(db, "bank_name")
            state_data["card_holder"] = await get_setting(db, "card_holder_name")
        elif method == "stars":
            toman_per_star = int(await get_setting(db, "stars_toman_per_star") or "1000")
            state_data["stars_amount"] = _stars_for_price(plan["price"], toman_per_star)
        elif method == "ton":
            toman_per_ton = int(await get_setting(db, "ton_toman_per_ton") or "50000000")
            state_data["ton_amount"] = _ton_for_price(plan["price"], toman_per_ton)
            state_data["ton_wallet"] = await get_setting(db, "ton_wallet_address")

    await state.set_state(PurchaseStates.waiting_for_config_name)
    await state.update_data(**state_data)
    await callback.message.answer(t("ask_config_name", lang), parse_mode="HTML")
    await callback.answer()
    logger.info(
        "User %d created order %d (%s), awaiting config name",
        callback.from_user.id, order_id, method,
    )


# ── Cancel ────────────────────────────────────────────────────────────────────

@router.message(PurchaseStates.waiting_for_config_name, Command("cancel"))
@router.message(PurchaseStates.waiting_for_receipt, Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, lang: str) -> None:
    data = await state.get_data()
    order_id = data.get("order_id")
    if order_id:
        async with get_db() as db:
            await cancel_order(db, order_id)
    await state.clear()
    await message.answer(t("purchase_cancelled", lang))
    logger.info("User %d cancelled order %d", message.from_user.id, order_id)


# ── Config name input ─────────────────────────────────────────────────────────

@router.message(PurchaseStates.waiting_for_config_name, F.text)
async def handle_config_name(message: Message, state: FSMContext, lang: str) -> None:
    name = message.text.strip()
    if len(name) > _NAME_MAX:
        await message.answer(t("name_too_long", lang))
        return

    error_key = validate_config_name(name)
    if error_key:
        await message.answer(t(error_key, lang), parse_mode="HTML")
        return

    try:
        available = await check_username_available(name)
    except MarzbanError:
        available = True

    if not available:
        await message.answer(t("name_taken", lang, name=name), parse_mode="HTML")
        return

    data = await state.get_data()
    method = data.get("payment_method", "card")
    order_id: int = data["order_id"]

    await state.update_data(config_name=name)

    if method == "card":
        await state.set_state(PurchaseStates.waiting_for_receipt)
        await message.answer(
            t("name_set_pay", lang,
              name=name,
              price=f"{data['price']:,}",
              currency=data["currency"],
              plan=data["plan_title"],
              card=data["card_number"],
              bank=data["bank_name"],
              holder=data["card_holder"]),
            parse_mode="HTML",
        )

    elif method == "ton":
        await state.set_state(PurchaseStates.waiting_for_receipt)
        await message.answer(
            t("name_set_pay_ton", lang,
              name=name,
              price=f"{data['price']:,}",
              currency=data["currency"],
              plan=data["plan_title"],
              ton_amount=data["ton_amount"],
              wallet=data["ton_wallet"]),
            parse_mode="HTML",
        )

    elif method == "stars":
        async with get_db() as db:
            await set_config_name(db, order_id, name)
        stars_amount: int = data["stars_amount"]
        plan_title: str = data["plan_title"]
        await state.clear()
        await message.answer_invoice(
            title=plan_title,
            description=t("stars_invoice_desc", lang, plan=plan_title, stars=stars_amount),
            payload=str(order_id),
            currency="XTR",
            prices=[LabeledPrice(label=plan_title, amount=stars_amount)],
        )
        await message.answer(t("stars_invoice_sent", lang), parse_mode="HTML")
        logger.info("Stars invoice sent for order %d (%d ⭐)", order_id, stars_amount)


@router.message(PurchaseStates.waiting_for_config_name, ~F.text)
async def config_name_non_text(message: Message, lang: str) -> None:
    await message.answer(t("send_text_name", lang))


# ── Receipt photo (card & TON) ─────────────────────────────────────────────────

@router.message(PurchaseStates.waiting_for_receipt, F.photo)
async def handle_receipt_photo(message: Message, state: FSMContext, bot: Bot, lang: str) -> None:
    data = await state.get_data()
    order_id: int = data["order_id"]
    config_name: str = data["config_name"]
    method: str = data.get("payment_method", "card")
    file_id = message.photo[-1].file_id

    async with get_db() as db:
        await set_receipt(db, order_id, file_id, config_name)
    await state.clear()

    await message.answer(t("receipt_received", lang))

    async with get_db() as db:
        order = await get_order(db, order_id)

    user = message.from_user
    user_tag = f"@{user.username}" if user.username else user.first_name
    method_label = "💎 TON" if method == "ton" else "💳 Card"
    caption = (
        f"📋 <b>New receipt — Order #{order_id}</b>\n\n"
        f"User: {user_tag} (ID: {user.id})\n"
        f"Plan: {order['title']}\n"
        f"Config name: {config_name}\n"
        f"Price: {order['price']:,} {data.get('currency', '')}\n"
        f"Payment: {method_label}"
    )
    await bot.send_photo(
        chat_id=settings.admin_telegram_id,
        photo=file_id,
        caption=caption,
        parse_mode="HTML",
        reply_markup=admin_review(order_id),
    )
    logger.info(
        "Receipt for order %d (%s, config=%r) sent to admin",
        order_id, method, config_name,
    )


@router.message(PurchaseStates.waiting_for_receipt, ~F.photo)
async def handle_non_photo(message: Message, lang: str) -> None:
    await message.answer(t("send_photo_reminder", lang), parse_mode="HTML")


# ── Telegram Stars payment handlers ───────────────────────────────────────────

@router.pre_checkout_query()
async def handle_pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message, bot: Bot) -> None:
    order_id = int(message.successful_payment.invoice_payload)
    logger.info("Stars payment received for order %d", order_id)

    async with get_db() as db:
        order = await get_order(db, order_id)

    if not order:
        logger.error("Stars payment for unknown order %d", order_id)
        await message.answer(
            "⚠️ Payment received but the order was not found. Please contact support."
        )
        await bot.send_message(
            settings.admin_telegram_id,
            f"⚠️ Stars payment received but order #{order_id} not found.",
        )
        return

    async with get_db() as db:
        plan = await get_plan(db, order["plan_id"])
        buyer_lang = await get_user_language(db, order["telegram_id"])

    await message.answer(t("stars_payment_success", buyer_lang))

    try:
        marzban_username, subscription_url = await create_subscription(
            telegram_id=order["telegram_id"],
            duration_days=plan["duration_days"],
            data_limit_gb=plan["data_limit_gb"],
            config_name=order["config_name"] or str(order["telegram_id"]),
        )
    except MarzbanError as exc:
        logger.error("Marzban error on Stars order %d: %s", order_id, exc)
        async with get_db() as db:
            await fail_order(db, order_id, str(exc))
        await message.answer(
            "⚠️ Payment confirmed but subscription setup failed. "
            "We'll resolve this manually — you will not lose your Stars."
        )
        await bot.send_message(
            settings.admin_telegram_id,
            f"⚠️ Stars payment received but Marzban failed for order #{order_id}: {exc}\n"
            f"User: {order['telegram_id']}",
        )
        return

    async with get_db() as db:
        await approve_order(db, order_id, marzban_username, subscription_url)
        updated_order = await get_order(db, order_id)

    expiry = (
        datetime.fromisoformat(updated_order["reviewed_at"])
        + timedelta(days=plan["duration_days"])
    ).strftime("%Y-%m-%d")

    await message.answer(
        t("approved_dm", buyer_lang,
          plan=order["title"],
          expiry=expiry,
          url=subscription_url),
        parse_mode="HTML",
    )
    logger.info("Stars order %d approved — Marzban user %s", order_id, marzban_username)
