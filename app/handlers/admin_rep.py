from __future__ import annotations

import logging
from typing import Union

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.db import get_db
from app.i18n import t
from app.keyboards import (
    admin_rep_actions_keyboard,
    admin_rep_charge_review,
    admin_rep_list_keyboard,
    admin_rep_settings_keyboard,
)
from app.repo.bot_settings import get_setting, set_setting
from app.repo.sales_reps import (
    approve_charge,
    create_rep,
    credit_gb,
    get_all_reps,
    get_charge,
    get_pending_charges,
    get_rep,
    get_rep_charges,
    reject_charge,
    set_rep_price_per_gb,
    toggle_rep_active,
)
from app.repo.users import get_user_language
from app.states import AdminRepStates
from configs.configs import settings

router = Router()
logger = logging.getLogger(__name__)


def _is_admin(user_id: int) -> bool:
    return user_id == settings.admin_telegram_id


def _fmt_gb(value: float) -> str:
    s = f"{value:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _cashback_gb(gb: float, threshold: float, percent: float) -> float:
    if gb >= threshold:
        return round(gb * percent / 100, 2)
    return 0.0


# ── Rep list ──────────────────────────────────────────────────────────────────

async def _show_rep_list(target: Union[Message, CallbackQuery]) -> None:
    async with get_db() as db:
        reps = await get_all_reps(db)

    text = (
        "<b>Sales Representatives</b>\n\n"
        f"Total: {len(reps)} rep(s)\n\n"
        "Tap a rep to manage, or use the buttons below."
    )
    kb = admin_rep_list_keyboard(reps)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data == "arep:list")
async def cb_arep_list(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    await _show_rep_list(callback)


# ── Add rep ───────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "arep:add")
async def cb_arep_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(AdminRepStates.waiting_for_rep_telegram_id)
    await callback.answer()
    await callback.message.answer(
        "Send the <b>Telegram ID</b> of the user to register as a sales rep.\n"
        "They must have already started the bot.\n\n"
        "Send /cancel to abort.",
        parse_mode="HTML",
    )


@router.message(AdminRepStates.waiting_for_rep_telegram_id, F.text)
async def handle_rep_telegram_id(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _is_admin(message.from_user.id):
        return

    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Cancelled.")
        return

    try:
        rep_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Invalid ID. Please send a numeric Telegram user ID.")
        return

    async with get_db() as db:
        existing_user = await db.fetchone(
            "SELECT * FROM users WHERE telegram_id = ?", (rep_id,)
        )

    if not existing_user:
        await message.answer(
            "❌ User not found in database. They must start the bot first."
        )
        return

    async with get_db() as db:
        existing_rep = await get_rep(db, rep_id)

    if existing_rep:
        status = "active" if existing_rep["is_active"] else "suspended"
        await message.answer(
            f"⚠️ User <code>{rep_id}</code> is already a sales representative ({status}).",
            parse_mode="HTML",
        )
        await state.clear()
        return

    async with get_db() as db:
        await create_rep(db, rep_id)

    await state.clear()

    name = (
        f"@{existing_user['username']}"
        if existing_user["username"]
        else existing_user["first_name"]
    )
    await message.answer(
        f"✅ <a href='tg://user?id={rep_id}'>{name}</a> (ID: <code>{rep_id}</code>) "
        f"has been added as a sales representative.",
        parse_mode="HTML",
    )

    try:
        await bot.send_message(
            chat_id=rep_id,
            text=(
                "🎉 You have been registered as a <b>Sales Representative</b>!\n\n"
                "You can now charge your GB wallet and create VPN configs "
                "for your customers.\n\n"
                "Tap /start to access your rep panel."
            ),
            parse_mode="HTML",
        )
    except Exception:
        logger.warning("Could not send welcome message to new rep %d", rep_id)

    logger.info("Admin added sales rep %d (%s)", rep_id, name)
    await _show_rep_list(message)


# ── View rep ──────────────────────────────────────────────────────────────────

async def _show_rep_detail(target: Union[Message, CallbackQuery], rep_id: int) -> None:
    async with get_db() as db:
        rep = await get_rep(db, rep_id)
        user = await db.fetchone(
            "SELECT * FROM users WHERE telegram_id = ?", (rep_id,)
        )
        charges = await get_rep_charges(db, rep_id, limit=5)

    if not rep:
        if isinstance(target, CallbackQuery):
            await target.answer("Rep not found.", show_alert=True)
        return

    name = (
        f"@{user['username']}"
        if user and user["username"]
        else (user["first_name"] if user else str(rep_id))
    )
    status = "✅ Active" if rep["is_active"] else "❌ Suspended"

    async with get_db() as db:
        global_price = int(await get_setting(db, "rep_price_per_gb") or "5000")
        currency = await get_setting(db, "currency_label") or ""

    custom_price = rep["price_per_gb"]
    if custom_price is not None:
        price_line = f"Price/GB: <b>{int(custom_price):,} {currency}</b> (custom)"
    else:
        price_line = f"Price/GB: {global_price:,} {currency} (global rate)"

    recent_charges = ""
    if charges:
        icons = {"approved": "✅", "pending_review": "⏳", "rejected": "❌"}
        lines = [
            f"  {icons.get(c['status'], '?')} {c['gb_amount']}GB — {c['created_at'][:10]}"
            for c in charges
        ]
        recent_charges = "\n\nRecent charges:\n" + "\n".join(lines)

    text = (
        f"<b>Sales Rep:</b> <a href='tg://user?id={rep_id}'>{name}</a>\n"
        f"ID: <code>{rep_id}</code>\n"
        f"Status: {status}\n"
        f"{price_line}\n\n"
        f"Balance: <b>{_fmt_gb(rep['gb_balance'])} GB</b>\n"
        f"Total Charged: {_fmt_gb(rep['total_charged'])} GB\n"
        f"Total Used: {_fmt_gb(rep['total_used'])} GB"
        f"{recent_charges}"
    )
    kb = admin_rep_actions_keyboard(rep_id, bool(rep["is_active"]), custom_price is not None)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith("arep:view:"))
async def cb_arep_view(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    rep_id = int(callback.data.split(":")[2])
    await _show_rep_detail(callback, rep_id)


# ── Toggle rep active ─────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("arep:toggle:"))
async def cb_arep_toggle(callback: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    rep_id = int(callback.data.split(":")[2])

    async with get_db() as db:
        new_active = await toggle_rep_active(db, rep_id)

    label = "activated" if new_active else "suspended"
    await callback.answer(f"Rep {label}.", show_alert=True)

    try:
        action_text = "activated ✅" if new_active else "suspended ❌"
        await bot.send_message(
            chat_id=rep_id,
            text=f"Your sales representative account has been {action_text}.",
        )
    except Exception:
        pass

    logger.info("Admin %s rep %d", label, rep_id)
    await _show_rep_detail(callback, rep_id)


# ── Pending charges list ──────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "arep:pending_charges")
async def cb_arep_pending_charges(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    async with get_db() as db:
        charges = await get_pending_charges(db)
        currency = await get_setting(db, "currency_label")

    if not charges:
        await callback.answer("No pending charge requests.", show_alert=True)
        return

    await callback.answer()
    for charge in charges:
        user_tag = (
            f"@{charge['username']}" if charge["username"] else charge["first_name"]
        )
        text = (
            f"#{charge['id']} | {user_tag} | "
            f"{charge['gb_amount']} GB | "
            f"{charge['total_price']:,} {currency}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="Open Receipt",
                callback_data=f"arep:open_charge:{charge['id']}",
            )
        ]])
        await callback.message.answer(text, reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith("arep:open_charge:"))
async def cb_arep_open_charge(callback: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    charge_id = int(callback.data.split(":")[2])

    async with get_db() as db:
        charge = await get_charge(db, charge_id)
        currency = await get_setting(db, "currency_label")

    if not charge:
        await callback.answer("Charge not found.", show_alert=True)
        return

    if not charge["receipt_file_id"]:
        await callback.answer("No receipt on file.", show_alert=True)
        return

    user_tag = (
        f"@{charge['username']}" if charge["username"] else charge["first_name"]
    )
    caption = (
        f"💼 <b>Rep Charge #{charge_id}</b>\n\n"
        f"Rep: {user_tag} (ID: <code>{charge['telegram_id']}</code>)\n"
        f"Amount: <b>{charge['gb_amount']} GB</b>\n"
        f"Total: <b>{charge['total_price']:,} {currency}</b>\n"
        f"Status: {charge['status']}"
    )
    await bot.send_photo(
        chat_id=settings.admin_telegram_id,
        photo=charge["receipt_file_id"],
        caption=caption,
        parse_mode="HTML",
        reply_markup=admin_rep_charge_review(charge_id),
    )
    await callback.answer()


# ── Approve charge ────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("arep:charge_approve:"))
async def cb_arep_charge_approve(callback: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    charge_id = int(callback.data.split(":")[2])

    async with get_db() as db:
        charge = await get_charge(db, charge_id)

    if not charge:
        await callback.answer("Charge not found.", show_alert=True)
        return

    if charge["status"] != "pending_review":
        await callback.answer(
            f"Charge is not pending (status: {charge['status']}).", show_alert=True
        )
        return

    await callback.answer("Processing…")

    async with get_db() as db:
        threshold = float(await get_setting(db, "rep_cashback_threshold_gb") or "40")
        percent = float(await get_setting(db, "rep_cashback_percent") or "5")

    gb_cashback = _cashback_gb(float(charge["gb_amount"]), threshold, percent)

    async with get_db() as db:
        await approve_charge(db, charge_id, gb_cashback)
        await credit_gb(db, charge["telegram_id"], float(charge["gb_amount"]), gb_cashback)
        rep = await get_rep(db, charge["telegram_id"])
        buyer_lang = await get_user_language(db, charge["telegram_id"])

    try:
        await callback.message.edit_caption(
            (callback.message.caption or "") + "\n\n✅ Approved by admin"
        )
    except Exception:
        pass

    cashback_line = ""
    if gb_cashback > 0:
        cashback_line = t(
            "rep_charge_cashback_credited", buyer_lang, cashback=_fmt_gb(gb_cashback)
        )

    await bot.send_message(
        chat_id=charge["telegram_id"],
        text=t("rep_charge_approved", buyer_lang,
               gb=charge["gb_amount"],
               cashback_line=cashback_line,
               balance=_fmt_gb(rep["gb_balance"])),
        parse_mode="HTML",
    )
    logger.info(
        "Admin approved rep charge #%d: %s GB + %s GB cashback",
        charge_id, charge["gb_amount"], gb_cashback,
    )


# ── Reject charge ─────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("arep:charge_reject:"))
async def cb_arep_charge_reject(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    charge_id = int(callback.data.split(":")[2])

    async with get_db() as db:
        charge = await get_charge(db, charge_id)

    if not charge or charge["status"] != "pending_review":
        await callback.answer("Charge is no longer pending.", show_alert=True)
        return

    await state.set_state(AdminRepStates.awaiting_charge_reject_reason)
    await state.update_data(charge_id=charge_id, admin_msg_id=callback.message.message_id)
    await callback.answer()
    await callback.message.answer(
        "Send the rejection reason for this charge request, or /cancel to abort."
    )


@router.message(AdminRepStates.awaiting_charge_reject_reason, F.text)
async def handle_charge_reject_reason(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _is_admin(message.from_user.id):
        return

    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Cancelled.")
        return

    data = await state.get_data()
    charge_id: int = data["charge_id"]
    reason = message.text.strip()

    async with get_db() as db:
        await reject_charge(db, charge_id, reason)
        charge = await get_charge(db, charge_id)
        buyer_lang = await get_user_language(db, charge["telegram_id"])

    await state.clear()

    try:
        await bot.edit_message_caption(
            chat_id=settings.admin_telegram_id,
            message_id=data["admin_msg_id"],
            caption=f"❌ Rejected: {reason}",
        )
    except Exception:
        pass

    await bot.send_message(
        chat_id=charge["telegram_id"],
        text=t("rep_charge_rejected", buyer_lang, reason=reason),
        parse_mode="HTML",
    )
    await message.answer(f"Charge #{charge_id} rejected.")
    logger.info("Admin rejected rep charge #%d: %s", charge_id, reason)


# ── Rep settings ──────────────────────────────────────────────────────────────

_REP_SETTING_LABELS: dict[str, str] = {
    "rep_price_per_gb":          "Price per GB",
    "rep_config_duration_days":  "Config Duration (days)",
    "rep_cashback_threshold_gb": "Cashback Threshold (GB)",
    "rep_cashback_percent":      "Cashback Percent (%)",
    "rep_min_config_gb":         "Min Config GB",
    "rep_max_config_gb":         "Max Config GB",
    "rep_min_charge_gb":         "Min Charge GB (per transaction)",
    "rep_max_charge_gb":         "Max Charge GB (per transaction, 0 = unlimited)",
    # Rep-specific card payment details
    "rep_card_number":           "Rep Card Number",
    "rep_bank_name":             "Rep Bank Name",
    "rep_card_holder_name":      "Rep Card Holder",
}

# Fields that accept free text (skip positive-number validation)
_REP_TEXT_FIELDS = {"rep_card_number", "rep_bank_name", "rep_card_holder_name"}
# Fields that allow zero (e.g. "0 = unlimited")
_REP_ZERO_OK_FIELDS = {"rep_max_charge_gb", "rep_max_config_gb"}


async def _show_rep_settings(target: Union[Message, CallbackQuery]) -> None:
    keys = list(_REP_SETTING_LABELS.keys()) + ["currency_label"]
    async with get_db() as db:
        ps = {k: await get_setting(db, k) for k in keys}

    card = ps.get("rep_card_number") or "—"
    bank = ps.get("rep_bank_name") or "—"
    holder = ps.get("rep_card_holder_name") or "—"

    min_charge = ps.get("rep_min_charge_gb") or "1"
    max_charge = ps.get("rep_max_charge_gb") or "0"
    charge_range = (
        f"{min_charge}–{max_charge} GB"
        if int(max_charge) > 0
        else f"{min_charge}+ GB (no max)"
    )

    text = (
        "<b>⚙️ Sales Rep Settings</b>\n\n"
        f"Price/GB: <b>{int(ps.get('rep_price_per_gb') or '5000'):,} "
        f"{ps.get('currency_label', '')}</b>\n"
        f"Config Duration: <b>{ps.get('rep_config_duration_days', '30')} days</b>\n"
        f"Cashback: <b>{ps.get('rep_cashback_percent', '5')}%</b> on "
        f"<b>{ps.get('rep_cashback_threshold_gb', '40')}+ GB</b>\n"
        f"Config Range: "
        f"<b>{ps.get('rep_min_config_gb', '5')}–{ps.get('rep_max_config_gb', '30')} GB</b>\n"
        f"Charge Range: <b>{charge_range}</b>\n\n"
        f"<b>Rep Card Payment</b>\n"
        f"Card: <code>{card}</code>\n"
        f"Bank: {bank}\n"
        f"Holder: {holder}\n\n"
        "Tap a setting to change it."
    )
    kb = admin_rep_settings_keyboard(ps)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data == "arep:settings")
async def cb_arep_settings(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    await _show_rep_settings(callback)


@router.callback_query(lambda c: c.data and c.data.startswith("arep:set:"))
async def cb_arep_set_field(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    field = callback.data.split(":", 2)[2]
    if field not in _REP_SETTING_LABELS:
        await callback.answer("Unknown setting.", show_alert=True)
        return

    async with get_db() as db:
        current = await get_setting(db, field)

    await state.set_state(AdminRepStates.editing_rep_setting)
    await state.update_data(rep_settings_field=field)
    await callback.answer()
    await callback.message.answer(
        f"Current <b>{_REP_SETTING_LABELS[field]}</b>: <code>{current or '—'}</code>\n\n"
        "Send the new value, or /cancel to abort.",
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("arep:set_price:"))
async def cb_arep_set_price(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    rep_id = int(callback.data.split(":")[2])

    async with get_db() as db:
        rep = await get_rep(db, rep_id)
        global_price = int(await get_setting(db, "rep_price_per_gb") or "5000")
        currency = await get_setting(db, "currency_label") or ""

    if not rep:
        await callback.answer("Rep not found.", show_alert=True)
        return

    current = rep["price_per_gb"]
    current_text = (
        f"{int(current):,} {currency} (custom)" if current is not None
        else f"{global_price:,} {currency} (global rate)"
    )

    await state.set_state(AdminRepStates.setting_rep_custom_price)
    await state.update_data(target_rep_id=rep_id)
    await callback.answer()
    await callback.message.answer(
        f"Current price for this rep: <b>{current_text}</b>\n\n"
        "Send a new price per GB (e.g. <code>8000</code>).\n"
        "Send <code>0</code> to remove the custom price and revert to the global rate.\n"
        "Send /cancel to abort.",
        parse_mode="HTML",
    )


@router.message(AdminRepStates.setting_rep_custom_price, F.text)
async def handle_rep_custom_price(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return

    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Cancelled.")
        return

    try:
        value = int(message.text.strip())
        if value < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Please send a non-negative whole number.")
        return

    data = await state.get_data()
    rep_id: int = data["target_rep_id"]

    # 0 means reset to global rate
    new_price = None if value == 0 else value

    async with get_db() as db:
        await set_rep_price_per_gb(db, rep_id, new_price)
        currency = await get_setting(db, "currency_label") or ""
        global_price = int(await get_setting(db, "rep_price_per_gb") or "5000")

    await state.clear()

    if new_price is None:
        result = f"reverted to global rate ({global_price:,} {currency})"
    else:
        result = f"set to <b>{new_price:,} {currency}/GB</b>"
    await message.answer(
        f"✅ Custom price for rep <code>{rep_id}</code> {result}.",
        parse_mode="HTML",
    )
    logger.info("Admin set custom price for rep %d: %s", rep_id, new_price)
    await _show_rep_detail(message, rep_id)


@router.message(AdminRepStates.editing_rep_setting, F.text)
async def handle_rep_settings_input(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return

    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Cancelled.")
        return

    data = await state.get_data()
    field: str = data["rep_settings_field"]
    value = message.text.strip()

    if field not in _REP_TEXT_FIELDS:
        try:
            num = float(value)
            if field in _REP_ZERO_OK_FIELDS:
                if num < 0:
                    raise ValueError
            else:
                if num <= 0:
                    raise ValueError
        except ValueError:
            if field in _REP_ZERO_OK_FIELDS:
                await message.answer("❌ Please send a non-negative number (0 = unlimited).")
            else:
                await message.answer("❌ Please send a positive number.")
            return

    async with get_db() as db:
        await set_setting(db, field, value)

    await state.clear()
    await message.answer(
        f"✅ <b>{_REP_SETTING_LABELS[field]}</b> updated to: <code>{value}</code>",
        parse_mode="HTML",
    )
    await _show_rep_settings(message)
    logger.info("Admin updated rep setting %s = %s", field, value)
