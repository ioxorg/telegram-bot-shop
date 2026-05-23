from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db import get_db
from app.i18n import t
from app.keyboards import rep_back_keyboard, rep_panel_keyboard
from app.marzban import MarzbanError, check_username_available, create_subscription, validate_config_name
from app.repo.bot_settings import get_setting
from app.repo.sales_reps import (
    create_charge,
    create_rep_config,
    deduct_gb,
    get_charge,
    get_rep,
    get_rep_configs,
    set_charge_receipt,
)
from app.states import SalesRepStates
from configs.configs import settings

router = Router()
logger = logging.getLogger(__name__)


def _fmt_gb(value: float) -> str:
    s = f"{value:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _cashback_gb(gb: float, threshold: float, percent: float) -> float:
    if gb >= threshold:
        return round(gb * percent / 100, 2)
    return 0.0


async def _assert_active_rep(callback: CallbackQuery, lang: str) -> bool:
    async with get_db() as db:
        rep = await get_rep(db, callback.from_user.id)
    if not rep:
        await callback.answer(t("rep_not_found", lang), show_alert=True)
        return False
    if not rep["is_active"]:
        await callback.answer(t("rep_suspended", lang), show_alert=True)
        return False
    return True


# ── Rep panel ─────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "rep:panel")
async def cb_rep_panel(callback: CallbackQuery, lang: str) -> None:
    async with get_db() as db:
        rep = await get_rep(db, callback.from_user.id)
    if not rep:
        await callback.answer(t("rep_not_found", lang), show_alert=True)
        return
    if not rep["is_active"]:
        await callback.answer(t("rep_suspended", lang), show_alert=True)
        return
    await callback.message.edit_text(
        t("rep_panel_title", lang, balance=_fmt_gb(rep["gb_balance"])),
        parse_mode="HTML",
        reply_markup=rep_panel_keyboard(lang),
    )
    await callback.answer()


# ── Wallet ────────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "rep:wallet")
async def cb_rep_wallet(callback: CallbackQuery, lang: str) -> None:
    if not await _assert_active_rep(callback, lang):
        return
    async with get_db() as db:
        rep = await get_rep(db, callback.from_user.id)
    await callback.message.edit_text(
        t("rep_wallet", lang,
          balance=_fmt_gb(rep["gb_balance"]),
          total_charged=_fmt_gb(rep["total_charged"]),
          total_used=_fmt_gb(rep["total_used"])),
        parse_mode="HTML",
        reply_markup=rep_back_keyboard(lang),
    )
    await callback.answer()


# ── Charge flow ───────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "rep:charge")
async def cb_rep_charge(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    if not await _assert_active_rep(callback, lang):
        return
    async with get_db() as db:
        rep = await get_rep(db, callback.from_user.id)
        global_price = int(await get_setting(db, "rep_price_per_gb") or "5000")
        currency = await get_setting(db, "currency_label") or "تومان"

    # Use rep's individual price if set, otherwise fall back to global rate
    price_per_gb = int(rep["price_per_gb"]) if rep["price_per_gb"] is not None else global_price

    await state.set_state(SalesRepStates.waiting_for_charge_amount)
    await state.update_data(price_per_gb=price_per_gb, currency=currency)
    await callback.answer()
    await callback.message.answer(
        t("rep_charge_prompt", lang,
          price=f"{price_per_gb:,}",
          currency=currency,
          balance=_fmt_gb(rep["gb_balance"])),
        parse_mode="HTML",
    )


@router.message(SalesRepStates.waiting_for_charge_amount, F.text)
async def handle_charge_amount(message: Message, state: FSMContext, lang: str) -> None:
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer(t("purchase_cancelled", lang))
        return

    try:
        gb = int(message.text.strip())
        if gb <= 0:
            raise ValueError
    except ValueError:
        await message.answer(t("rep_charge_invalid_amount", lang))
        return

    data = await state.get_data()
    price_per_gb: int = data["price_per_gb"]
    currency: str = data["currency"]
    total_price = gb * price_per_gb

    async with get_db() as db:
        threshold = float(await get_setting(db, "rep_cashback_threshold_gb") or "40")
        percent = float(await get_setting(db, "rep_cashback_percent") or "5")
        card = await get_setting(db, "rep_card_number") or ""
        bank = await get_setting(db, "rep_bank_name") or ""
        holder = await get_setting(db, "rep_card_holder_name") or ""

    if not card:
        await state.clear()
        await message.answer(t("rep_charge_no_card", lang))
        return

    cashback = _cashback_gb(gb, threshold, percent)
    final_gb = gb + cashback

    cashback_line = ""
    if cashback > 0:
        cashback_line = t("rep_charge_cashback_line", lang,
                          percent=int(percent),
                          threshold=int(threshold),
                          cashback=_fmt_gb(cashback))

    async with get_db() as db:
        charge_id = await create_charge(db, message.from_user.id, gb, price_per_gb, total_price)

    await state.update_data(
        charge_id=charge_id,
        gb_amount=gb,
        cashback=cashback,
        final_gb=final_gb,
    )
    await state.set_state(SalesRepStates.waiting_for_charge_receipt)

    await message.answer(
        t("rep_charge_summary", lang,
          gb=gb,
          price=f"{price_per_gb:,}",
          currency=currency,
          total=f"{total_price:,}",
          cashback_line=cashback_line,
          final_gb=_fmt_gb(final_gb),
          card=card,
          bank=bank,
          holder=holder),
        parse_mode="HTML",
    )


@router.message(SalesRepStates.waiting_for_charge_receipt, F.photo)
async def handle_charge_receipt(message: Message, state: FSMContext, bot: Bot, lang: str) -> None:
    data = await state.get_data()
    charge_id: int = data["charge_id"]
    gb_amount: int = data["gb_amount"]
    cashback: float = data["cashback"]
    final_gb: float = data["final_gb"]

    file_id = message.photo[-1].file_id

    async with get_db() as db:
        await set_charge_receipt(db, charge_id, file_id)
        charge = await get_charge(db, charge_id)
        currency = await get_setting(db, "currency_label")

    await state.clear()
    await message.answer(t("rep_charge_receipt_received", lang), parse_mode="HTML")

    user_tag = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.first_name
    )
    cashback_info = f"\nCashback: +{_fmt_gb(cashback)} GB" if cashback > 0 else ""

    caption = (
        f"💼 <b>Rep Charge Request #{charge_id}</b>\n\n"
        f"Rep: <a href='tg://user?id={message.from_user.id}'>{user_tag}</a> "
        f"(ID: <code>{message.from_user.id}</code>)\n"
        f"Requested: <b>{gb_amount} GB</b>{cashback_info}\n"
        f"Final GB: <b>{_fmt_gb(final_gb)} GB</b>\n"
        f"Total: <b>{charge['total_price']:,} {currency}</b>"
    )

    from app.keyboards import admin_rep_charge_review
    try:
        await bot.send_photo(
            chat_id=settings.admin_telegram_id,
            photo=file_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=admin_rep_charge_review(charge_id),
        )
    except Exception:
        logger.exception("Failed to notify admin of rep charge #%d", charge_id)

    logger.info(
        "Rep %d submitted charge receipt for #%d (%d GB)",
        message.from_user.id, charge_id, gb_amount,
    )


@router.message(SalesRepStates.waiting_for_charge_receipt, ~F.photo)
async def handle_charge_receipt_not_photo(message: Message, lang: str) -> None:
    await message.answer(t("send_photo_reminder", lang), parse_mode="HTML")


# ── Config creation ───────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "rep:create_config")
async def cb_rep_create_config(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    if not await _assert_active_rep(callback, lang):
        return

    async with get_db() as db:
        rep = await get_rep(db, callback.from_user.id)
        min_gb = int(await get_setting(db, "rep_min_config_gb") or "5")

    balance = rep["gb_balance"]
    if balance < min_gb:
        await callback.answer(
            t("rep_config_insufficient_balance", lang,
              balance=_fmt_gb(balance), min_gb=min_gb),
            show_alert=True,
        )
        return

    await state.set_state(SalesRepStates.waiting_for_config_name)
    await callback.answer()
    await callback.message.answer(
        t("rep_create_config_start", lang, balance=_fmt_gb(balance)),
        parse_mode="HTML",
    )


@router.message(SalesRepStates.waiting_for_config_name, F.text)
async def handle_rep_config_name(message: Message, state: FSMContext, lang: str) -> None:
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer(t("purchase_cancelled", lang))
        return

    name = message.text.strip()

    if len(name) > 32:
        await message.answer(t("name_too_long", lang), parse_mode="HTML")
        return

    err_key = validate_config_name(name)
    if err_key:
        await message.answer(t(err_key, lang), parse_mode="HTML")
        return

    try:
        available = await check_username_available(name)
    except MarzbanError as exc:
        await message.answer(f"⚠️ Error checking name: {exc}")
        return

    if not available:
        await message.answer(t("name_taken", lang, name=name), parse_mode="HTML")
        return

    async with get_db() as db:
        rep = await get_rep(db, message.from_user.id)
        min_gb = int(await get_setting(db, "rep_min_config_gb") or "5")
        max_gb = int(await get_setting(db, "rep_max_config_gb") or "30")

    await state.update_data(config_name=name)
    await state.set_state(SalesRepStates.waiting_for_config_gb)

    await message.answer(
        t("rep_ask_gb", lang,
          name=name,
          min=min_gb,
          max=max_gb,
          balance=_fmt_gb(rep["gb_balance"])),
        parse_mode="HTML",
    )


@router.message(SalesRepStates.waiting_for_config_gb, F.text)
async def handle_rep_config_gb(message: Message, state: FSMContext, lang: str) -> None:
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer(t("purchase_cancelled", lang))
        return

    async with get_db() as db:
        min_gb = int(await get_setting(db, "rep_min_config_gb") or "5")
        max_gb = int(await get_setting(db, "rep_max_config_gb") or "30")

    try:
        gb = int(message.text.strip())
    except ValueError:
        await message.answer(t("rep_gb_invalid", lang, min=min_gb, max=max_gb))
        return

    if gb < min_gb or gb > max_gb:
        await message.answer(t("rep_gb_invalid", lang, min=min_gb, max=max_gb))
        return

    async with get_db() as db:
        rep = await get_rep(db, message.from_user.id)
        duration_days = int(await get_setting(db, "rep_config_duration_days") or "30")

    balance = rep["gb_balance"]
    if balance < gb:
        await message.answer(
            t("rep_gb_no_balance", lang, balance=_fmt_gb(balance), requested=gb),
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    config_name: str = data["config_name"]

    processing_msg = await message.answer(t("rep_config_creating", lang))

    try:
        marzban_username, subscription_url = await create_subscription(
            telegram_id=message.from_user.id,
            duration_days=duration_days,
            data_limit_gb=gb,
            config_name=config_name,
        )
    except MarzbanError as exc:
        logger.error("Marzban error creating rep config for %d: %s", message.from_user.id, exc)
        await state.clear()
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await message.answer(t("rep_config_error", lang), parse_mode="HTML")
        return

    async with get_db() as db:
        await deduct_gb(db, message.from_user.id, gb)
        await create_rep_config(
            db,
            rep_telegram_id=message.from_user.id,
            config_name=config_name,
            gb_allocated=gb,
            duration_days=duration_days,
            marzban_username=marzban_username,
            subscription_url=subscription_url,
        )
        rep = await get_rep(db, message.from_user.id)

    await state.clear()
    try:
        await processing_msg.delete()
    except Exception:
        pass

    await message.answer(
        t("rep_config_created", lang,
          name=config_name,
          gb=gb,
          days=duration_days,
          balance=_fmt_gb(rep["gb_balance"]),
          url=subscription_url),
        parse_mode="HTML",
    )
    logger.info(
        "Rep %d created config %s (%d GB / %d days)",
        message.from_user.id, config_name, gb, duration_days,
    )


# ── My configs ────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "rep:my_configs")
async def cb_rep_my_configs(callback: CallbackQuery, lang: str) -> None:
    if not await _assert_active_rep(callback, lang):
        return

    async with get_db() as db:
        configs = await get_rep_configs(db, callback.from_user.id, limit=15)

    if not configs:
        await callback.message.edit_text(
            t("rep_no_configs", lang),
            parse_mode="HTML",
            reply_markup=rep_back_keyboard(lang),
        )
        await callback.answer()
        return

    lines = [
        t("rep_config_item", lang,
          name=c["config_name"],
          gb=f"{c['gb_allocated']:.0f}",
          date=c["created_at"][:10])
        for c in configs
    ]
    await callback.message.edit_text(
        t("rep_configs_list", lang, count=len(configs), items="\n".join(lines)),
        parse_mode="HTML",
        reply_markup=rep_back_keyboard(lang),
    )
    await callback.answer()
