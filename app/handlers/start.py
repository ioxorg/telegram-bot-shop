from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, User

from app.db import get_db
from app.i18n import t
from app.keyboards import language_picker, main_menu, phone_request_keyboard
from app.repo.users import get_phone_number, set_user_language, upsert_user
from app.states import VerificationStates
from configs.configs import settings

router = Router()
logger = logging.getLogger(__name__)


async def _dismiss_reply_keyboard(message: Message) -> None:
    sent = await message.answer("...", reply_markup=ReplyKeyboardRemove())
    await sent.delete()


async def _send_sticker(message: Message) -> None:
    if settings.welcome_sticker_id:
        await message.answer_sticker(settings.welcome_sticker_id)


async def _ask_for_phone(message: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(VerificationStates.waiting_for_phone)
    await message.answer(t("ask_phone", lang), reply_markup=phone_request_keyboard(lang), parse_mode="HTML")


async def _notify_admin_new_user(bot: Bot, user: User) -> None:
    name = f"@{user.username}" if user.username else user.first_name
    await bot.send_message(
        settings.admin_telegram_id,
        f"👤 New user joined: <a href='tg://user?id={user.id}'>{name}</a> (ID: <code>{user.id}</code>)",
        parse_mode="HTML",
    )


@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot, state: FSMContext, lang: str) -> None:
    is_admin = message.from_user.id == settings.admin_telegram_id

    async with get_db() as db:
        is_new = await upsert_user(db, message.from_user)
        phone = await get_phone_number(db, message.from_user.id)

    await _dismiss_reply_keyboard(message)
    await _send_sticker(message)

    if is_new:
        await message.answer(t("welcome_new", lang), reply_markup=language_picker())
        if not is_admin:
            try:
                await _notify_admin_new_user(bot, message.from_user)
            except Exception:
                pass
        return

    # Existing user — gate on phone verification (skip for admin)
    if not phone and not is_admin:
        await _ask_for_phone(message, state, lang)
        return

    await message.answer(t("welcome", lang), reply_markup=main_menu(lang, is_admin=is_admin))
    logger.info("User %d opened main menu (lang=%s)", message.from_user.id, lang)


@router.callback_query(lambda c: c.data == "lang:select")
async def cb_lang_select(callback: CallbackQuery, lang: str) -> None:
    await callback.message.edit_text(
        t("choose_language", lang), reply_markup=language_picker()
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("lang:set:"))
async def cb_lang_set(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    new_lang = callback.data.split(":")[2]
    is_admin = callback.from_user.id == settings.admin_telegram_id

    async with get_db() as db:
        await set_user_language(db, callback.from_user.id, new_lang)
        phone = await get_phone_number(db, callback.from_user.id)

    await callback.answer()
    await _send_sticker(callback.message)

    if not phone and not is_admin:
        await _ask_for_phone(callback.message, state, new_lang)
        logger.info("User %d set language to %s — awaiting phone", callback.from_user.id, new_lang)
        return

    await callback.message.answer(
        t("welcome", new_lang),
        reply_markup=main_menu(new_lang, is_admin=is_admin),
    )
    logger.info("User %d set language to %s", callback.from_user.id, new_lang)


@router.callback_query(lambda c: c.data in ("menu:back", "menu:main"))
async def cb_back_to_menu(callback: CallbackQuery, lang: str) -> None:
    is_admin = callback.from_user.id == settings.admin_telegram_id
    await callback.message.edit_text(
        t("welcome", lang), reply_markup=main_menu(lang, is_admin=is_admin)
    )
    await callback.answer()
