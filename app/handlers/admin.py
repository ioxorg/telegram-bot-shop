from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.db import get_db
from app.i18n import t
from app.keyboards import admin_payment_settings, admin_plan_actions, admin_plans_list, admin_review
from app.marzban import MarzbanError, create_subscription
from app.repo.orders import (
    approve_order,
    count_approved,
    fail_order,
    get_failed_orders,
    get_order,
    get_pending_orders,
    reject_order,
    total_revenue,
)
from app.repo.bot_settings import (
    get_payment_settings,
    get_setting,
    set_setting,
    toggle_force_join,
    toggle_nowpayments,
    toggle_payment_enabled,
    toggle_phone_verification,
    toggle_stars_payment,
)
from app.repo.plans import (
    create_plan,
    delete_plan,
    get_all_plans,
    get_plan,
    get_plan_any,
    toggle_plan,
    update_plan,
)
from app.repo.users import count_users, get_user_language
from app.states import AdminForceJoinStates, AdminPlanStates, AdminSettingsStates, AdminStates
from configs.configs import settings

router = Router()
logger = logging.getLogger(__name__)

_PLAN_FORMAT_HELP = (
    "Send plan details in this format:\n"
    "<code>DATA_GB DAYS USER_LIMIT PRICE</code>\n\n"
    "Examples:\n"
    "  <code>50 30 2 150000</code>  — 50 GB, 30 days, 2 users, 150,000\n"
    "  <code>0 30 1 99000</code>    — Unlimited data, 30 days, 1 user\n"
    "  <code>100 90 0 400000</code> — 100 GB, 90 days, unlimited users\n\n"
    "Use 0 for unlimited data or unlimited users.\n"
    "Send /cancel to abort."
)


def _is_admin(user_id: int) -> bool:
    return user_id == settings.admin_telegram_id


def _parse_plan_input(text: str) -> tuple[int, int, int, int]:
    parts = text.strip().split()
    if len(parts) != 4:
        raise ValueError("Expected exactly 4 values: DATA_GB DAYS USER_LIMIT PRICE")
    data_gb, days, users, price = (int(p) for p in parts)
    if data_gb < 0 or days <= 0 or users < 0 or price <= 0:
        raise ValueError("Invalid values: days and price must be > 0; others >= 0")
    return data_gb, days, users, price


def _plan_summary(plan, currency: str = "") -> str:
    data = "∞ GB" if plan["data_limit_gb"] == 0 else f"{plan['data_limit_gb']} GB"
    users = "∞ Users" if plan["user_limit"] == 0 else f"{plan['user_limit']} User"
    status = "✅ Active" if plan["is_active"] else "❌ Inactive"
    return (
        f"<b>Plan #{plan['id']}</b>\n"
        f"{data} – {plan['duration_days']} Days – {users}\n"
        f"Price: <b>{plan['price']:,} {currency}</b>\n"
        f"Status: {status}"
    )


# ── Approve ──────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("admin:approve:"))
async def cb_approve(callback: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    order_id = int(callback.data.split(":")[2])

    async with get_db() as db:
        order = await get_order(db, order_id)

    if not order:
        await callback.answer("Order not found.", show_alert=True)
        return

    if order["status"] != "pending_review":
        await callback.answer(
            f"Order is no longer pending (status: {order['status']}).", show_alert=True
        )
        return

    await callback.answer("Processing…")

    async with get_db() as db:
        plan = await get_plan(db, order["plan_id"])

    try:
        marzban_username, subscription_url = await create_subscription(
            telegram_id=order["telegram_id"],
            duration_days=plan["duration_days"],
            data_limit_gb=plan["data_limit_gb"],
            config_name=order["config_name"] or str(order["telegram_id"]),
        )
    except MarzbanError as exc:
        logger.error("Marzban error on order %d: %s", order_id, exc)
        async with get_db() as db:
            await fail_order(db, order_id, str(exc))
        await callback.message.edit_caption(
            (callback.message.caption or "") + "\n\n⚠️ Marzban error — see /failed_orders"
        )
        await bot.send_message(
            settings.admin_telegram_id,
            f"⚠️ Failed to create subscription for order #{order_id}: {exc}",
        )
        return

    async with get_db() as db:
        await approve_order(db, order_id, marzban_username, subscription_url)
        updated_order = await get_order(db, order_id)
        buyer_lang = await get_user_language(db, order["telegram_id"])

    expiry = (
        datetime.fromisoformat(updated_order["reviewed_at"])
        + timedelta(days=plan["duration_days"])
    ).strftime("%Y-%m-%d")

    await callback.message.edit_caption(
        (callback.message.caption or "") + "\n\n✅ Approved by admin"
    )

    await bot.send_message(
        chat_id=order["telegram_id"],
        text=t("approved_dm", buyer_lang,
               plan=order["title"],
               expiry=expiry,
               url=subscription_url),
        parse_mode="HTML",
    )
    logger.info("Order %d approved — Marzban user %s created", order_id, marzban_username)


# ── Reject ───────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("admin:reject:"))
async def cb_reject(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    order_id = int(callback.data.split(":")[2])

    async with get_db() as db:
        order = await get_order(db, order_id)

    if not order or order["status"] != "pending_review":
        await callback.answer("Order is no longer pending.", show_alert=True)
        return

    await state.set_state(AdminStates.awaiting_reject_reason)
    await state.update_data(order_id=order_id, admin_msg_id=callback.message.message_id)
    await callback.answer()
    await callback.message.answer("Send the rejection reason as a message.")


@router.message(AdminStates.awaiting_reject_reason, F.text)
async def handle_reject_reason(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _is_admin(message.from_user.id):
        return

    data = await state.get_data()
    order_id: int = data["order_id"]
    reason = message.text.strip()

    async with get_db() as db:
        await reject_order(db, order_id, reason)
        order = await get_order(db, order_id)
        buyer_lang = await get_user_language(db, order["telegram_id"])

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
        chat_id=order["telegram_id"],
        text=t("rejected_dm", buyer_lang, reason=reason),
        parse_mode="HTML",
    )
    await message.answer(f"Order #{order_id} rejected.")
    logger.info("Order %d rejected: %s", order_id, reason)


# ── Open order from /pending ──────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("admin:open:"))
async def cb_admin_open(callback: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    order_id = int(callback.data.split(":")[2])

    async with get_db() as db:
        order = await get_order(db, order_id)
        currency = await get_setting(db, "currency_label")

    if not order:
        await callback.answer("Order not found.", show_alert=True)
        return

    if not order["receipt_file_id"]:
        await callback.answer("No receipt on file.", show_alert=True)
        return

    caption = (
        f"📋 <b>Order #{order_id}</b>\n"
        f"Plan: {order['title']}\n"
        f"Price: {order['price']:,} {currency}\n"
        f"Status: {order['status']}"
    )
    await bot.send_photo(
        chat_id=settings.admin_telegram_id,
        photo=order["receipt_file_id"],
        caption=caption,
        parse_mode="HTML",
        reply_markup=admin_review(order_id),
    )
    await callback.answer()


# ── Admin text commands ──────────────────────────────────────────────────────

@router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    async with get_db() as db:
        orders = await get_pending_orders(db)

    if not orders:
        await message.answer("No pending orders.")
        return

    async with get_db() as db:
        currency = await get_setting(db, "currency_label")

    for order in orders:
        user_tag = f"@{order['username']}" if order["username"] else order["first_name"]
        text = (
            f"#{order['id']} | {user_tag} | {order['title']} | "
            f"{order['price']:,} {currency}"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Open", callback_data=f"admin:open:{order['id']}")]]
        )
        await message.answer(text, reply_markup=kb)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    async with get_db() as db:
        users = await count_users(db)
        approved = await count_approved(db)
        revenue = await total_revenue(db)
        currency = await get_setting(db, "currency_label")

    await message.answer(
        f"<b>Stats</b>\n\n"
        f"Total users: {users:,}\n"
        f"Approved orders: {approved:,}\n"
        f"Total revenue: {revenue:,} {currency}",
        parse_mode="HTML",
    )


@router.message(Command("failed_orders"))
async def cmd_failed_orders(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    async with get_db() as db:
        orders = await get_failed_orders(db)

    if not orders:
        await message.answer("No failed orders.")
        return

    async with get_db() as db:
        currency = await get_setting(db, "currency_label")

    lines = ["<b>Failed orders:</b>\n"]
    for order in orders:
        user_tag = f"@{order['username']}" if order["username"] else order["first_name"]
        lines.append(
            f"#{order['id']} | {user_tag} | {order['title']} | "
            f"{order['reviewed_at'] or '?'}\n  ↳ {order['admin_note']}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── Admin panel ──────────────────────────────────────────────────────────────

async def _show_admin_panel(target: Message | CallbackQuery) -> None:
    async with get_db() as db:
        verify_on = await get_setting(db, "phone_verification_enabled") == "1"
        force_join_on = await get_setting(db, "force_join_enabled") == "1"
        force_join_channel = await get_setting(db, "force_join_channel") or "not set"

    verify_label = (
        f"{'🟢' if verify_on else '🔴'} Phone Verification: "
        f"{'ON → Disable' if verify_on else 'OFF → Enable'}"
    )
    force_join_label = (
        f"{'🟢' if force_join_on else '🔴'} Force Join: "
        f"{force_join_channel if force_join_on else 'OFF'}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Manage Plans", callback_data="aplan:list")],
        [InlineKeyboardButton(text="💳 Payment Settings", callback_data="apay:show")],
        [InlineKeyboardButton(text="👥 Sales Reps", callback_data="arep:list")],
        [InlineKeyboardButton(text=verify_label, callback_data="admin:toggle_verify")],
        [InlineKeyboardButton(text=f"📢 {force_join_label}", callback_data="admin:force_join")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:back")],
    ])
    text = (
        "<b>Admin panel</b>\n\n"
        "/pending — list pending receipts\n"
        "/stats — sales statistics\n"
        "/failed_orders — failed Marzban orders\n"
        "/plans — manage plans\n"
        "/payment — payment settings"
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data == "menu:admin")
async def cb_admin_panel(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    await _show_admin_panel(callback)


@router.callback_query(lambda c: c.data == "admin:toggle_verify")
async def cb_toggle_verification(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    async with get_db() as db:
        now_on = await toggle_phone_verification(db)
    await callback.answer(
        f"Phone verification {'enabled' if now_on else 'disabled'}.", show_alert=True
    )
    await _show_admin_panel(callback)
    logger.info("Admin %s phone verification", "enabled" if now_on else "disabled")


# ── Force Join Channel ───────────────────────────────────────────────────────

async def _show_force_join_settings(target: Message | CallbackQuery) -> None:
    async with get_db() as db:
        enabled = await get_setting(db, "force_join_enabled") == "1"
        channel = await get_setting(db, "force_join_channel") or "Not set"

    status = "🟢 ON" if enabled else "🔴 OFF"
    toggle_label = f"{'🟢 ON → Disable' if enabled else '🔴 OFF → Enable'}"
    text = (
        f"<b>📢 Force Join Channel</b>\n\n"
        f"Status: {status}\n"
        f"Channel: <code>{channel}</code>\n\n"
        "When enabled, users must join the channel before using the bot."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_label, callback_data="admin:toggle_force_join")],
        [InlineKeyboardButton(text="✏️ Set Channel", callback_data="admin:set_force_join_channel")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:admin")],
    ])
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data == "admin:force_join")
async def cb_force_join(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    await _show_force_join_settings(callback)


@router.callback_query(lambda c: c.data == "admin:toggle_force_join")
async def cb_toggle_force_join(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    async with get_db() as db:
        now_on = await toggle_force_join(db)
    await callback.answer(
        f"Force join {'enabled' if now_on else 'disabled'}.", show_alert=True
    )
    await _show_force_join_settings(callback)
    logger.info("Admin %s force join channel", "enabled" if now_on else "disabled")


@router.callback_query(lambda c: c.data == "admin:set_force_join_channel")
async def cb_set_force_join_channel(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    await state.set_state(AdminForceJoinStates.waiting_for_channel)
    await callback.answer()
    await callback.message.answer(
        "Send the channel username (e.g. <code>@mychannel</code>), or /cancel to abort.",
        parse_mode="HTML",
    )


@router.message(AdminForceJoinStates.waiting_for_channel, F.text)
async def handle_force_join_channel(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Cancelled.")
        return
    channel = "@" + message.text.strip().lstrip("@")
    async with get_db() as db:
        await set_setting(db, "force_join_channel", channel)
    await state.clear()
    await message.answer(
        f"✅ Force join channel set to <code>{channel}</code>.",
        parse_mode="HTML",
    )
    await _show_force_join_settings(message)
    logger.info("Admin set force join channel to %s", channel)


# ── Plan management ──────────────────────────────────────────────────────────

async def _show_plans_list(target: Message | CallbackQuery) -> None:
    async with get_db() as db:
        plans = await get_all_plans(db)
    text = "<b>Plans</b>\n\nTap a plan to manage it, or add a new one."
    kb = admin_plans_list(plans)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("plans"))
async def cmd_plans(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await _show_plans_list(message)


@router.callback_query(lambda c: c.data == "aplan:list")
async def cb_plans_list(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    await _show_plans_list(callback)


@router.callback_query(lambda c: c.data and c.data.startswith("aplan:view:"))
async def cb_plan_view(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    plan_id = int(callback.data.split(":")[2])
    async with get_db() as db:
        plan = await get_plan_any(db, plan_id)

    if not plan:
        await callback.answer("Plan not found.", show_alert=True)
        return

    async with get_db() as db:
        currency = await get_setting(db, "currency_label")

    await callback.message.edit_text(
        _plan_summary(plan, currency),
        parse_mode="HTML",
        reply_markup=admin_plan_actions(plan_id, bool(plan["is_active"])),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("aplan:toggle:"))
async def cb_plan_toggle(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    plan_id = int(callback.data.split(":")[2])
    async with get_db() as db:
        new_state = await toggle_plan(db, plan_id)
        plan = await get_plan_any(db, plan_id)
        currency = await get_setting(db, "currency_label")

    if plan is None:
        await callback.answer("Plan not found.", show_alert=True)
        return

    state_label = "activated" if new_state else "deactivated"
    await callback.answer(f"Plan {state_label}.")
    await callback.message.edit_text(
        _plan_summary(plan, currency),
        parse_mode="HTML",
        reply_markup=admin_plan_actions(plan_id, new_state),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("aplan:delete:"))
async def cb_plan_delete(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    plan_id = int(callback.data.split(":")[2])
    async with get_db() as db:
        await delete_plan(db, plan_id)

    await callback.answer("Plan deleted.")
    await _show_plans_list(callback)


@router.callback_query(lambda c: c.data == "aplan:add")
async def cb_plan_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(AdminPlanStates.waiting_for_new_plan)
    await callback.answer()
    await callback.message.answer(_PLAN_FORMAT_HELP, parse_mode="HTML")


@router.message(AdminPlanStates.waiting_for_new_plan, F.text)
async def handle_new_plan(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return

    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Cancelled.")
        return

    try:
        data_gb, days, users, price = _parse_plan_input(message.text)
    except ValueError as e:
        await message.answer(f"❌ {e}\n\n{_PLAN_FORMAT_HELP}", parse_mode="HTML")
        return

    async with get_db() as db:
        plan_id = await create_plan(db, data_gb, days, users, price)
        plan = await get_plan_any(db, plan_id)

    async with get_db() as db:
        currency = await get_setting(db, "currency_label")
    await state.clear()
    await message.answer(
        f"✅ Plan created!\n\n{_plan_summary(plan, currency)}",
        parse_mode="HTML",
        reply_markup=admin_plan_actions(plan_id, True),
    )
    logger.info("Admin created plan #%d: %dGB/%dd/%du @ %d", plan_id, data_gb, days, users, price)


@router.callback_query(lambda c: c.data and c.data.startswith("aplan:edit:"))
async def cb_plan_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    plan_id = int(callback.data.split(":")[2])
    async with get_db() as db:
        plan = await get_plan_any(db, plan_id)

    if not plan:
        await callback.answer("Plan not found.", show_alert=True)
        return

    await state.set_state(AdminPlanStates.waiting_for_edit_plan)
    await state.update_data(plan_id=plan_id)
    await callback.answer()

    current = (
        f"Current: <code>{plan['data_limit_gb']} {plan['duration_days']} "
        f"{plan['user_limit']} {plan['price']}</code>\n\n"
    )
    await callback.message.answer(
        current + _PLAN_FORMAT_HELP, parse_mode="HTML"
    )


@router.message(AdminPlanStates.waiting_for_edit_plan, F.text)
async def handle_edit_plan(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return

    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Cancelled.")
        return

    data = await state.get_data()
    plan_id: int = data["plan_id"]

    try:
        data_gb, days, users, price = _parse_plan_input(message.text)
    except ValueError as e:
        await message.answer(f"❌ {e}\n\n{_PLAN_FORMAT_HELP}", parse_mode="HTML")
        return

    async with get_db() as db:
        await update_plan(db, plan_id, data_gb, days, users, price)
        plan = await get_plan_any(db, plan_id)

    async with get_db() as db:
        currency = await get_setting(db, "currency_label")
    await state.clear()
    await message.answer(
        f"✅ Plan updated!\n\n{_plan_summary(plan, currency)}",
        parse_mode="HTML",
        reply_markup=admin_plan_actions(plan_id, bool(plan["is_active"])),
    )
    logger.info("Admin updated plan #%d: %dGB/%dd/%du @ %d", plan_id, data_gb, days, users, price)


# ── Payment settings management ──────────────────────────────────────────────

_FIELD_LABELS = {
    "card_number":        "Card Number",
    "bank_name":          "Bank Name",
    "card_holder_name":   "Card Holder",
    "currency_label":     "Currency",
    "stars_toman_per_star": "Stars Rate (toman per 1 ⭐)",
    "usd_toman_rate":     "USD Rate (toman per $1)",
}

_FIELD_STATE = {
    "card_number":        AdminSettingsStates.editing_card_number,
    "bank_name":          AdminSettingsStates.editing_bank_name,
    "card_holder_name":   AdminSettingsStates.editing_card_holder,
    "currency_label":     AdminSettingsStates.editing_currency,
    "stars_toman_per_star": AdminSettingsStates.editing_stars_rate,
    "usd_toman_rate":     AdminSettingsStates.editing_usd_rate,
}


def _status(enabled: bool) -> str:
    return "🟢 On" if enabled else "🔴 Off"


async def _show_payment_settings(target: Message | CallbackQuery) -> None:
    async with get_db() as db:
        ps = await get_payment_settings(db)
    card_on  = ps.get("card_payment_enabled", "1") == "1"
    stars_on = ps.get("stars_payment_enabled", "0") == "1"
    np_on    = ps.get("nowpayments_enabled", "0") == "1"
    np_key   = bool(settings.nowpayments_api_key)
    text = (
        "<b>💳 Payment Settings</b>\n\n"
        f"💳 Card:   {_status(card_on)}\n"
        f"⭐ Stars:  {_status(stars_on)} — {int(ps.get('stars_toman_per_star', '1000')):,} toman/star\n"
        f"💎 Crypto: {_status(np_on)} — $1 = {int(ps.get('usd_toman_rate', '600000')):,} toman"
        + ("" if np_key else "  ⚠️ NOWPAYMENTS_API_KEY not set") + "\n\n"
        f"Card Number: <code>{ps['card_number'] or '—'}</code>\n"
        f"Bank: {ps['bank_name'] or '—'}\n"
        f"Holder: {ps['card_holder_name'] or '—'}\n"
        f"Currency: {ps['currency_label'] or '—'}\n\n"
        "Tap a button to toggle or edit."
    )
    kb = admin_payment_settings(ps, nowpayments_key_set=np_key)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("payment"))
async def cmd_payment(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await _show_payment_settings(message)


@router.callback_query(lambda c: c.data == "apay:show")
async def cb_payment_show(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    await _show_payment_settings(callback)


@router.callback_query(lambda c: c.data == "apay:toggle_enabled")
async def cb_payment_toggle_enabled(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    async with get_db() as db:
        now_on = await toggle_payment_enabled(db)
    await callback.answer(f"Card payments {'enabled' if now_on else 'disabled'}.", show_alert=True)
    await _show_payment_settings(callback)
    logger.info("Admin %s card payments", "enabled" if now_on else "disabled")


@router.callback_query(lambda c: c.data == "apay:toggle_stars")
async def cb_payment_toggle_stars(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    async with get_db() as db:
        now_on = await toggle_stars_payment(db)
    await callback.answer(f"Stars payments {'enabled' if now_on else 'disabled'}.", show_alert=True)
    await _show_payment_settings(callback)
    logger.info("Admin %s Stars payments", "enabled" if now_on else "disabled")


@router.callback_query(lambda c: c.data == "apay:toggle_nowpayments")
async def cb_payment_toggle_nowpayments(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    if not settings.nowpayments_api_key:
        await callback.answer(
            "Set NOWPAYMENTS_API_KEY in your .env first.", show_alert=True
        )
        return
    async with get_db() as db:
        now_on = await toggle_nowpayments(db)
    await callback.answer(f"Crypto payments {'enabled' if now_on else 'disabled'}.", show_alert=True)
    await _show_payment_settings(callback)
    logger.info("Admin %s NOWPayments crypto", "enabled" if now_on else "disabled")


@router.callback_query(lambda c: c.data and c.data.startswith("apay:edit:"))
async def cb_payment_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    field = callback.data.split(":")[2]
    if field not in _FIELD_STATE:
        await callback.answer("Unknown field.", show_alert=True)
        return

    async with get_db() as db:
        current = await get_setting(db, field)

    await state.set_state(_FIELD_STATE[field])
    await state.update_data(settings_field=field)
    await callback.answer()
    await callback.message.answer(
        f"Current <b>{_FIELD_LABELS[field]}</b>: <code>{current or '—'}</code>\n\n"
        "Send the new value, or /cancel to abort.",
        parse_mode="HTML",
    )


async def _handle_settings_input(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Cancelled.")
        return
    data = await state.get_data()
    field: str = data["settings_field"]
    value = message.text.strip()
    async with get_db() as db:
        await set_setting(db, field, value)
    await state.clear()
    await message.answer(
        f"✅ <b>{_FIELD_LABELS[field]}</b> updated to: <code>{value}</code>",
        parse_mode="HTML",
    )
    await _show_payment_settings(message)
    logger.info("Admin updated payment setting %s", field)


@router.message(AdminSettingsStates.editing_card_number, F.text)
@router.message(AdminSettingsStates.editing_bank_name, F.text)
@router.message(AdminSettingsStates.editing_card_holder, F.text)
@router.message(AdminSettingsStates.editing_currency, F.text)
@router.message(AdminSettingsStates.editing_stars_rate, F.text)
@router.message(AdminSettingsStates.editing_usd_rate, F.text)
async def handle_settings_input(message: Message, state: FSMContext) -> None:
    await _handle_settings_input(message, state)
