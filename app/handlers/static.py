from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.i18n import t
from configs.configs import settings

router = Router()


@router.callback_query(lambda c: c.data == "menu:how_to")
async def cb_how_to(callback: CallbackQuery, lang: str) -> None:
    rows = [[InlineKeyboardButton(text=t("btn_back", lang), callback_data="menu:back")]]
    await callback.message.edit_text(
        t("how_to_title", lang, text=settings.how_to_connect_text),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()
