from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject

from app.db import get_db
from app.i18n import t
from app.keyboards import main_menu
from app.repo.bot_settings import get_setting
from app.repo.users import get_user_language
from configs.configs import settings

logger = logging.getLogger(__name__)


class LanguageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            async with get_db() as db:
                data["lang"] = await get_user_language(db, user.id)
        else:
            data["lang"] = "fa"
        return await handler(event, data)


async def _check_membership(bot: Bot, channel: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status not in ("left", "kicked", "banned")
    except Exception:
        return True  # fail-open: allow access if membership can't be verified


class ForceJoinMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bot: Bot | None = data.get("bot")
        user = data.get("event_from_user")

        if not user or not bot:
            return await handler(event, data)

        if user.id == settings.admin_telegram_id:
            return await handler(event, data)

        async with get_db() as db:
            enabled = await get_setting(db, "force_join_enabled") == "1"
            channel = await get_setting(db, "force_join_channel")
            lang = await get_user_language(db, user.id)

        if not enabled or not channel:
            return await handler(event, data)

        # Handle the "I Joined" check inline — re-check and respond
        if isinstance(event, CallbackQuery) and event.data == "force_join:check":
            if await _check_membership(bot, channel, user.id):
                await event.message.edit_text(
                    t("welcome", lang),
                    reply_markup=main_menu(lang, is_admin=False),
                )
                await event.answer()
            else:
                await event.answer(t("force_join_not_yet", lang), show_alert=True)
            return

        if await _check_membership(bot, channel, user.id):
            return await handler(event, data)

        # Gate the user: show join prompt
        channel_url = f"https://t.me/{channel.lstrip('@')}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t("force_join_btn", lang), url=channel_url)],
            [InlineKeyboardButton(text=t("force_join_check_btn", lang), callback_data="force_join:check")],
        ])
        if isinstance(event, Message):
            await event.answer(t("force_join_required", lang), reply_markup=kb)
        elif isinstance(event, CallbackQuery):
            await event.answer(t("force_join_not_yet", lang), show_alert=True)
        logger.debug("Blocked user %d — not a member of %s", user.id, channel)
