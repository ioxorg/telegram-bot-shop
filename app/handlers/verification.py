from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from app.db import get_db
from app.i18n import t
from app.keyboards import main_menu
from app.repo.users import set_phone_number
from app.states import VerificationStates
from configs.configs import settings

router = Router()
logger = logging.getLogger(__name__)


def _normalize_phone(raw: str) -> str | None:
    """Normalize to +98XXXXXXXXXX; return None if the number is not Iranian."""
    p = raw.strip().replace(" ", "").replace("-", "")
    if p.startswith("+98") and len(p) == 13 and p[3:].isdigit():
        return p
    if p.startswith("98") and len(p) == 12 and p[2:].isdigit():
        return "+" + p
    if p.startswith("09") and len(p) == 11 and p[1:].isdigit():
        return "+98" + p[1:]
    return None


async def _finish_verification(message: Message, state: FSMContext, phone: str, lang: str) -> None:
    async with get_db() as db:
        await set_phone_number(db, message.from_user.id, phone)
    await state.clear()
    is_admin = message.from_user.id == settings.admin_telegram_id
    await message.answer(
        t("phone_verified", lang, phone=phone),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
    await message.answer(t("welcome", lang), reply_markup=main_menu(lang, is_admin=is_admin))
    logger.info("User %d verified phone %s", message.from_user.id, phone)


@router.message(VerificationStates.waiting_for_phone, F.contact)
async def handle_phone_contact(message: Message, state: FSMContext, lang: str) -> None:
    # Only accept the user's own contact (Telegram guarantees this via request_contact)
    if message.contact.user_id != message.from_user.id:
        await message.answer(t("phone_not_yours", lang))
        return

    phone = _normalize_phone(message.contact.phone_number)
    if not phone:
        await message.answer(t("phone_invalid", lang), parse_mode="HTML")
        return

    await _finish_verification(message, state, phone, lang)


@router.message(VerificationStates.waiting_for_phone, F.text)
async def handle_phone_text(message: Message, state: FSMContext, lang: str) -> None:
    phone = _normalize_phone(message.text)
    if not phone:
        await message.answer(t("phone_invalid", lang), parse_mode="HTML")
        return

    await _finish_verification(message, state, phone, lang)


@router.message(VerificationStates.waiting_for_phone)
async def handle_phone_wrong_type(message: Message, lang: str) -> None:
    await message.answer(t("phone_invalid", lang), parse_mode="HTML")
