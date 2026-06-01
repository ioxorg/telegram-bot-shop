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
from app.keyboards import admin_review, nowpay_keyboard, payment_method_keyboard
from app.panel import PanelError, check_username_available, create_subscription, validate_config_name
from app.nowpayments import NowPaymentsError, SUCCESS_STATUSES, FAILED_STATUSES, create_invoice, get_payments_for_invoice
from app.repo.bot_settings import get_active_payment_methods, get_setting
from app.repo.orders import (
    approve_order,
    cancel_order,
    create_order,
    fail_order,
    get_order,
    set_config_name,
    set_nowpayments_id,
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


def _toman_to_usd(toman: int, usd_toman_rate: int) -> float:
    return round(toman / usd_toman_rate, 2)


# ── Plan paid — payment method selection ──────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("plan:paid:"))
async def cb_plan_paid(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    plan_id = int(callback.data.split(":")[2])

    async with get_db() as db:
        methods = await get_active_payment_methods(db, settings.nowpayments_api_key)
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

    async with get_db() as db:
        methods = await get_active_payment_methods(db, settings.nowpayments_api_key)
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
            state_data["bank_name"]   = await get_setting(db, "bank_name")
            state_data["card_holder"] = await get_setting(db, "card_holder_name")
        elif method == "stars":
            toman_per_star = int(await get_setting(db, "stars_toman_per_star") or "1000")
            state_data["stars_amount"] = _stars_for_price(plan["price"], toman_per_star)

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
    except PanelError:
        available = True

    if not available:
        await message.answer(t("name_taken", lang, name=name), parse_mode="HTML")
        return

    data = await state.get_data()
    method   = data.get("payment_method", "card")
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

    elif method == "stars":
        async with get_db() as db:
            await set_config_name(db, order_id, name)
        stars_amount: int = data["stars_amount"]
        plan_title: str   = data["plan_title"]
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

    elif method == "nowpayments":
        async with get_db() as db:
            await set_config_name(db, order_id, name)
            usd_rate = int(await get_setting(db, "usd_toman_rate") or "600000")
        await state.clear()

        usd_amount = _toman_to_usd(data["price"], usd_rate)
        if usd_amount < 0.50:
            await message.answer(t("nowpay_usd_too_low", lang), parse_mode="HTML")
            return

        try:
            invoice = await create_invoice(
                api_key=settings.nowpayments_api_key,
                price_usd=usd_amount,
                order_id=order_id,
                description=data["plan_title"],
                proxy_url=settings.telegram_proxy_url or None,
            )
        except NowPaymentsError as exc:
            logger.error("NOWPayments create_invoice failed for order %d: %s", order_id, exc)
            await message.answer(t("nowpay_error", lang))
            return

        invoice_id  = str(invoice["id"])
        invoice_url = invoice["invoice_url"]

        async with get_db() as db:
            await set_nowpayments_id(db, order_id, invoice_id)

        await message.answer(
            t("nowpay_invoice", lang, usd_amount=f"{usd_amount:.2f}"),
            parse_mode="HTML",
            reply_markup=nowpay_keyboard(invoice_url, order_id, lang),
        )
        logger.info(
            "NOWPayments invoice created for order %d — id=%s $%.2f",
            order_id, invoice_id, usd_amount,
        )


@router.message(PurchaseStates.waiting_for_config_name, ~F.text)
async def config_name_non_text(message: Message, lang: str) -> None:
    await message.answer(t("send_text_name", lang))


# ── NOWPayments — check payment status ───────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("nowpay:check:"))
async def cb_nowpay_check(callback: CallbackQuery, bot: Bot, lang: str) -> None:
    # nowpay:check:{order_id}
    order_id = int(callback.data.split(":")[2])

    await callback.answer()

    async with get_db() as db:
        order = await get_order(db, order_id)

    if not order:
        await callback.message.answer("Order not found.")
        return

    if order["status"] == "approved":
        await callback.message.answer(t("nowpay_already_approved", lang))
        return

    invoice_id = order["nowpayments_id"]
    if not invoice_id:
        await callback.message.answer(t("nowpay_waiting", lang))
        return

    try:
        payments = await get_payments_for_invoice(
            settings.nowpayments_api_key,
            settings.nowpayments_email,
            settings.nowpayments_password,
            invoice_id,
            proxy_url=settings.telegram_proxy_url or None,
        )
    except NowPaymentsError as exc:
        logger.error("NOWPayments status check failed for order %d: %s", order_id, exc)
        await callback.message.answer(t("nowpay_error", lang))
        return

    if not payments:
        await callback.message.answer(t("nowpay_waiting", lang))
        return

    latest     = payments[0]
    status     = latest.get("payment_status", "")
    payment_id = str(latest.get("payment_id", ""))
    logger.info("NOWPayments status for order %d (payment %s): %s", order_id, payment_id, status)

    if status in SUCCESS_STATUSES:
        await _approve_nowpayments_order(callback.message, bot, order, payment_id, lang)
    elif status in FAILED_STATUSES:
        await callback.message.answer(t("nowpay_failed", lang))
    elif status == "confirming":
        await callback.message.answer(t("nowpay_confirming", lang))
    else:
        await callback.message.answer(t("nowpay_waiting", lang))


async def _approve_nowpayments_order(
    message: Message,
    bot: Bot,
    order,
    payment_id: str,
    lang: str,
) -> None:
    order_id = order["id"]

    async with get_db() as db:
        plan = await get_plan(db, order["plan_id"])

    try:
        marzban_username, subscription_url = await create_subscription(
            telegram_id=order["telegram_id"],
            duration_days=plan["duration_days"],
            data_limit_gb=plan["data_limit_gb"],
            config_name=order["config_name"] or str(order["telegram_id"]),
        )
    except PanelError as exc:
        logger.error("Panel error after NOWPayments confirm, order %d: %s", order_id, exc)
        async with get_db() as db:
            await fail_order(db, order_id, str(exc))
        await message.answer(t("nowpay_marzban_fail", lang))
        await bot.send_message(
            settings.admin_telegram_id,
            f"⚠️ NOWPayments confirmed but panel failed for order #{order_id}\n"
            f"Payment ID: {payment_id}\nUser: {order['telegram_id']}\nError: {exc}",
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
        t("approved_dm", lang,
          plan=order["title"],
          expiry=expiry,
          url=subscription_url),
        parse_mode="HTML",
    )
    await bot.send_message(
        settings.admin_telegram_id,
        f"✅ Crypto order #{order_id} auto-approved (NOWPayments {payment_id})\n"
        f"User: {order['telegram_id']} — {order['title']}",
    )
    logger.info("NOWPayments order %d auto-approved — panel user %s", order_id, marzban_username)


# ── Receipt photo (card) ──────────────────────────────────────────────────────

@router.message(PurchaseStates.waiting_for_receipt, F.photo)
async def handle_receipt_photo(message: Message, state: FSMContext, bot: Bot, lang: str) -> None:
    data        = await state.get_data()
    order_id    = data["order_id"]
    config_name = data["config_name"]
    file_id     = message.photo[-1].file_id

    async with get_db() as db:
        await set_receipt(db, order_id, file_id, config_name)
    await state.clear()

    await message.answer(t("receipt_received", lang))

    async with get_db() as db:
        order    = await get_order(db, order_id)
        currency = data.get("currency", "")

    user     = message.from_user
    user_tag = f"@{user.username}" if user.username else user.first_name
    caption  = (
        f"📋 <b>New receipt — Order #{order_id}</b>\n\n"
        f"User: {user_tag} (ID: {user.id})\n"
        f"Plan: {order['title']}\n"
        f"Config name: {config_name}\n"
        f"Price: {order['price']:,} {currency}\n"
        f"Payment: 💳 Card"
    )
    await bot.send_photo(
        chat_id=settings.admin_telegram_id,
        photo=file_id,
        caption=caption,
        parse_mode="HTML",
        reply_markup=admin_review(order_id),
    )
    logger.info("Receipt for order %d (config=%r) sent to admin", order_id, config_name)


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
        plan       = await get_plan(db, order["plan_id"])
        buyer_lang = await get_user_language(db, order["telegram_id"])

    await message.answer(t("stars_payment_success", buyer_lang))

    try:
        marzban_username, subscription_url = await create_subscription(
            telegram_id=order["telegram_id"],
            duration_days=plan["duration_days"],
            data_limit_gb=plan["data_limit_gb"],
            config_name=order["config_name"] or str(order["telegram_id"]),
        )
    except PanelError as exc:
        logger.error("Panel error on Stars order %d: %s", order_id, exc)
        async with get_db() as db:
            await fail_order(db, order_id, str(exc))
        await message.answer(
            "⚠️ Payment confirmed but subscription setup failed. "
            "We'll resolve this manually — you will not lose your Stars."
        )
        await bot.send_message(
            settings.admin_telegram_id,
            f"⚠️ Stars payment received but panel failed for order #{order_id}: {exc}\n"
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
    logger.info("Stars order %d approved — panel user %s", order_id, marzban_username)
