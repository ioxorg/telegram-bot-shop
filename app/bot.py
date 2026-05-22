from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

from app.db import get_db, init_db
from app.handlers import admin, config, my_subs, plans, purchase, start, static, verification
from app.middleware import ForceJoinMiddleware, LanguageMiddleware
from app.repo.bot_settings import seed_payment_settings
from configs.configs import settings

logger = logging.getLogger(__name__)

_USER_COMMANDS = [
    BotCommand(command="start", description="Main menu"),
    BotCommand(command="buy", description="Browse plans and buy a subscription"),
    BotCommand(command="my_subs", description="My active subscriptions"),
    BotCommand(command="cancel", description="Cancel current action"),
]

_USER_COMMANDS_FA = [
    BotCommand(command="start", description="منوی اصلی"),
    BotCommand(command="buy", description="مشاهده پلن‌ها و خرید اشتراک"),
    BotCommand(command="my_subs", description="اشتراک‌های فعال من"),
    BotCommand(command="cancel", description="لغو عملیات جاری"),
]

_ADMIN_COMMANDS = _USER_COMMANDS + [
    BotCommand(command="pending", description="Pending orders awaiting review"),
    BotCommand(command="stats", description="Sales statistics"),
    BotCommand(command="failed_orders", description="Failed Marzban orders"),
    BotCommand(command="plans", description="Manage plans"),
    BotCommand(command="payment", description="Payment settings"),
]

_ADMIN_COMMANDS_FA = _USER_COMMANDS_FA + [
    BotCommand(command="pending", description="سفارش‌های در انتظار بررسی"),
    BotCommand(command="stats", description="آمار فروش"),
    BotCommand(command="failed_orders", description="سفارش‌های ناموفق Marzban"),
    BotCommand(command="plans", description="مدیریت پلن‌ها"),
    BotCommand(command="payment", description="تنظیمات پرداخت"),
]


async def _setup_menu(bot: Bot) -> None:
    # Persian is the default (shown when no language-specific match exists).
    # English is registered as the "en" locale for users with an English Telegram client.
    await bot.set_my_commands(_USER_COMMANDS_FA, scope=BotCommandScopeDefault())
    await bot.set_my_commands(_USER_COMMANDS, scope=BotCommandScopeDefault(), language_code="en")
    await bot.set_my_commands(
        _ADMIN_COMMANDS_FA,
        scope=BotCommandScopeChat(chat_id=settings.admin_telegram_id),
    )
    await bot.set_my_commands(
        _ADMIN_COMMANDS,
        scope=BotCommandScopeChat(chat_id=settings.admin_telegram_id),
        language_code="en",
    )
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Bot menu and commands configured")


async def main() -> None:
    await init_db()
    async with get_db() as db:
        await seed_payment_settings(
            db,
            card_number=settings.initial_card_number,
            card_holder_name=settings.initial_card_holder_name,
            currency_label=settings.initial_currency_label,
        )

    session: AiohttpSession | None = None
    if settings.telegram_proxy_url:
        session = AiohttpSession(proxy=settings.telegram_proxy_url)
        logger.info("Telegram requests will go through proxy %s", settings.telegram_proxy_url)

    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(LanguageMiddleware())
    dp.callback_query.middleware(LanguageMiddleware())
    dp.message.middleware(ForceJoinMiddleware())
    dp.callback_query.middleware(ForceJoinMiddleware())

    dp.include_router(start.router)
    dp.include_router(verification.router)
    dp.include_router(plans.router)
    dp.include_router(purchase.router)
    dp.include_router(my_subs.router)
    dp.include_router(config.router)
    dp.include_router(static.router)
    dp.include_router(admin.router)

    await _setup_menu(bot)

    logger.info("Bot polling started")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
