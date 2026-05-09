from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.i18n import t
from configs.configs import settings


def _plan_label(plan, currency: str) -> str:
    data = "∞ GB" if plan["data_limit_gb"] == 0 else f"{plan['data_limit_gb']} GB"
    users = "∞ Users" if plan["user_limit"] == 0 else f"{plan['user_limit']} User"
    return f"{data} – {plan['duration_days']} Days – {users} | {plan['price']:,} {currency}"


def main_menu(lang: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t("btn_buy", lang), callback_data="menu:buy")],
        [InlineKeyboardButton(text=t("btn_my_subs", lang), callback_data="menu:my_subs")],
        [InlineKeyboardButton(text=t("btn_how_to", lang), callback_data="menu:how_to")],
    ]
    if settings.support_url:
        rows.append([InlineKeyboardButton(text=t("btn_support", lang), url=settings.support_url)])
    rows.append([InlineKeyboardButton(text=t("btn_language", lang), callback_data="lang:select")])
    if is_admin:
        rows.append([InlineKeyboardButton(text=t("btn_admin", lang), callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def phone_request_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("btn_share_phone", lang), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def language_picker() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:set:en"),
            InlineKeyboardButton(text="🇮🇷 فارسی", callback_data="lang:set:fa"),
        ]
    ])


def plan_list(plans: list, lang: str, currency: str = "") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=_plan_label(p, currency),
            callback_data=f"plan:select:{p['id']}",
        )]
        for p in plans
    ]
    rows.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plan_detail(plan_id: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("btn_buy_plan", lang), callback_data=f"plan:paid:{plan_id}")],
        [InlineKeyboardButton(text=t("btn_back", lang), callback_data="menu:buy")],
    ])


def admin_review(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"admin:approve:{order_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"admin:reject:{order_id}"),
        ]
    ])


def order_open(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Open", callback_data=f"admin:open:{order_id}")]
    ])


def admin_plans_list(plans: list) -> InlineKeyboardMarkup:
    rows = []
    for p in plans:
        data = "∞" if p["data_limit_gb"] == 0 else f"{p['data_limit_gb']}GB"
        users = "∞" if p["user_limit"] == 0 else str(p["user_limit"])
        status = "✅" if p["is_active"] else "❌"
        label = f"{status} {data} – {p['duration_days']}d – {users}👤 – {p['price']:,}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"aplan:view:{p['id']}")])
    rows.append([InlineKeyboardButton(text="➕ Add Plan", callback_data="aplan:add")])
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_plan_actions(plan_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Deactivate" if is_active else "🟢 Activate"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=f"aplan:toggle:{plan_id}")],
        [InlineKeyboardButton(text="✏️ Edit", callback_data=f"aplan:edit:{plan_id}")],
        [InlineKeyboardButton(text="🗑 Delete", callback_data=f"aplan:delete:{plan_id}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="aplan:list")],
    ])


def payment_method_keyboard(plan_id: int, lang: str, methods: dict[str, bool]) -> InlineKeyboardMarkup:
    rows = []
    if methods.get("card"):
        rows.append([InlineKeyboardButton(text=t("btn_pay_card", lang), callback_data=f"plan:method:card:{plan_id}")])
    if methods.get("stars"):
        rows.append([InlineKeyboardButton(text=t("btn_pay_stars", lang), callback_data=f"plan:method:stars:{plan_id}")])
    if methods.get("ton"):
        rows.append([InlineKeyboardButton(text=t("btn_pay_ton", lang), callback_data=f"plan:method:ton:{plan_id}")])
    rows.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data="menu:buy")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_payment_settings(ps: dict) -> InlineKeyboardMarkup:
    card = ps.get("card_number") or "—"
    bank = ps.get("bank_name") or "—"
    holder = ps.get("card_holder_name") or "—"
    currency = ps.get("currency_label") or "—"
    card_on = ps.get("card_payment_enabled", "1") == "1"
    stars_on = ps.get("stars_payment_enabled", "0") == "1"
    ton_on = ps.get("ton_payment_enabled", "0") == "1"
    stars_rate = ps.get("stars_toman_per_star", "1000")
    ton_wallet = ps.get("ton_wallet_address") or "Not set"
    ton_rate = ps.get("ton_toman_per_ton", "50000000")

    def _tog(label: str, on: bool) -> str:
        return f"{'🟢' if on else '🔴'} {label}: {'ON → Disable' if on else 'OFF → Enable'}"

    wallet_short = ton_wallet[:22] + ("…" if len(ton_wallet) > 22 else "")
    return InlineKeyboardMarkup(inline_keyboard=[
        # ── Card ──
        [InlineKeyboardButton(text=_tog("Card", card_on), callback_data="apay:toggle_enabled")],
        [InlineKeyboardButton(text=f"💳 {card}", callback_data="apay:edit:card_number")],
        [InlineKeyboardButton(text=f"🏦 {bank}", callback_data="apay:edit:bank_name")],
        [InlineKeyboardButton(text=f"👤 {holder}", callback_data="apay:edit:card_holder_name")],
        [InlineKeyboardButton(text=f"💰 {currency}", callback_data="apay:edit:currency_label")],
        # ── Stars ──
        [InlineKeyboardButton(text=_tog("⭐ Stars", stars_on), callback_data="apay:toggle_stars")],
        [InlineKeyboardButton(text=f"⭐ Rate: {int(stars_rate):,} toman / star", callback_data="apay:edit:stars_toman_per_star")],
        # ── TON ──
        [InlineKeyboardButton(text=_tog("💎 TON", ton_on), callback_data="apay:toggle_ton")],
        [InlineKeyboardButton(text=f"💎 Wallet: {wallet_short}", callback_data="apay:edit:ton_wallet_address")],
        [InlineKeyboardButton(text=f"💱 Rate: {int(ton_rate):,} toman / TON", callback_data="apay:edit:ton_toman_per_ton")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:admin")],
    ])
