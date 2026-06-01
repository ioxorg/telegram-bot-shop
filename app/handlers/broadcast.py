from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.db import get_db
from app.repo.users import count_users, get_all_telegram_ids
from app.states import BroadcastStates
from configs.configs import settings

router = Router()
logger = logging.getLogger(__name__)

# ~28 msg/sec — safely under Telegram's 30/sec per-bot limit
_SEND_DELAY = 0.035
# How often to update the progress message (every N users)
_PROGRESS_EVERY = 50


def _is_admin(user_id: int) -> bool:
    return user_id == settings.admin_telegram_id


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Send as copy", callback_data="bc:confirm:copy"),
            InlineKeyboardButton(text="↩️ Forward",      callback_data="bc:confirm:forward"),
        ],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="bc:cancel")],
    ])


# ── /broadcast command ────────────────────────────────────────────────────────

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.set_state(BroadcastStates.waiting_for_message)
    await message.answer(
        "📡 <b>Broadcast</b>\n\n"
        "Send or forward the message you want to broadcast to all users.\n\n"
        "Send /cancel to abort.",
        parse_mode="HTML",
    )


@router.message(BroadcastStates.waiting_for_message, Command("cancel"))
async def cmd_broadcast_cancel(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("Broadcast cancelled.")


# ── Receive the message to broadcast ─────────────────────────────────────────

@router.message(BroadcastStates.waiting_for_message)
async def handle_broadcast_message(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return

    async with get_db() as db:
        total = await count_users(db)

    await state.update_data(
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )
    await state.set_state(BroadcastStates.confirming)

    await message.answer(
        f"👆 <b>Preview above.</b>\n\n"
        f"This will be sent to <b>{total:,}</b> users.\n\n"
        "<b>Send as copy</b> — no «Forwarded from» header\n"
        "<b>Forward</b> — shows your name as the source",
        parse_mode="HTML",
        reply_markup=_confirm_keyboard(),
    )


# ── Confirm ───────────────────────────────────────────────────────────────────

@router.callback_query(
    BroadcastStates.confirming,
    lambda c: c.data and c.data.startswith("bc:confirm:"),
)
async def cb_broadcast_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    mode = callback.data.split(":")[2]  # "copy" or "forward"
    data = await state.get_data()
    from_chat_id: int = data["from_chat_id"]
    message_id: int = data["message_id"]

    await state.clear()
    await callback.answer()

    async with get_db() as db:
        user_ids = await get_all_telegram_ids(db)

    total = len(user_ids)
    status_msg = await callback.message.edit_text(
        f"📡 Broadcasting to <b>{total:,}</b> users…",
        parse_mode="HTML",
    )

    sent = failed = 0

    for i, uid in enumerate(user_ids, 1):
        try:
            if mode == "forward":
                await bot.forward_message(
                    chat_id=uid,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                )
            else:
                await bot.copy_message(
                    chat_id=uid,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                )
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            # User blocked the bot or account no longer exists
            failed += 1
        except Exception as exc:
            logger.warning("Broadcast to user %d failed: %s", uid, exc)
            failed += 1

        if i % _PROGRESS_EVERY == 0:
            try:
                await status_msg.edit_text(
                    f"📡 Broadcasting… <b>{i}/{total}</b>\n"
                    f"✅ {sent:,}  ❌ {failed:,}",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        await asyncio.sleep(_SEND_DELAY)

    await status_msg.edit_text(
        f"✅ <b>Broadcast complete</b>\n\n"
        f"Sent:   <b>{sent:,}</b>\n"
        f"Failed: <b>{failed:,}</b>\n"
        f"Total:  <b>{total:,}</b>",
        parse_mode="HTML",
    )
    logger.info(
        "Broadcast complete — sent %d, failed %d, total %d", sent, failed, total
    )


# ── Cancel ────────────────────────────────────────────────────────────────────

@router.callback_query(BroadcastStates.confirming, lambda c: c.data == "bc:cancel")
async def cb_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("❌ Broadcast cancelled.")
