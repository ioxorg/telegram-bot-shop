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


def main_menu(lang: str, is_admin: bool = False, is_rep: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t("btn_buy", lang), callback_data="menu:buy")],
        [InlineKeyboardButton(text=t("btn_my_subs", lang), callback_data="menu:my_subs")],
        [InlineKeyboardButton(text=t("btn_how_to", lang), callback_data="menu:how_to")],
    ]
    if settings.support_url:
        rows.append([InlineKeyboardButton(text=t("btn_support", lang), url=settings.support_url)])
    rows.append([InlineKeyboardButton(text=t("btn_language", lang), callback_data="lang:select")])
    if is_rep:
        rows.append([InlineKeyboardButton(text=t("btn_rep_panel", lang), callback_data="rep:panel")])
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
    if methods.get("nowpayments"):
        rows.append([InlineKeyboardButton(text=t("btn_pay_crypto", lang), callback_data=f"plan:method:nowpayments:{plan_id}")])
    rows.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data="menu:buy")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nowpay_keyboard(invoice_url: str, order_id: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("nowpay_open_btn", lang), url=invoice_url)],
        [InlineKeyboardButton(
            text=t("nowpay_check_btn", lang),
            callback_data=f"nowpay:check:{order_id}",
        )],
    ])


# ── Sales rep keyboards ───────────────────────────────────────────────────────

def rep_panel_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("rep_btn_wallet", lang), callback_data="rep:wallet")],
        [InlineKeyboardButton(text=t("rep_btn_charge", lang), callback_data="rep:charge")],
        [InlineKeyboardButton(text=t("rep_btn_create_config", lang), callback_data="rep:create_config")],
        [InlineKeyboardButton(text=t("rep_btn_my_configs", lang), callback_data="rep:my_configs")],
        [InlineKeyboardButton(text=t("btn_back", lang), callback_data="menu:back")],
    ])


def rep_back_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("btn_back", lang), callback_data="rep:panel")],
    ])


def admin_rep_list_keyboard(reps: list) -> InlineKeyboardMarkup:
    rows = []
    for r in reps:
        name = f"@{r['username']}" if r["username"] else r["first_name"]
        status = "✅" if r["is_active"] else "❌"
        balance = f"{r['gb_balance']:.1f}".rstrip("0").rstrip(".")
        label = f"{status} {name} — {balance} GB"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"arep:view:{r['telegram_id']}")])
    rows.append([InlineKeyboardButton(text="➕ Add Rep", callback_data="arep:add")])
    rows.append([InlineKeyboardButton(text="📋 Pending Charges", callback_data="arep:pending_charges")])
    rows.append([InlineKeyboardButton(text="⚙️ Rep Settings", callback_data="arep:settings")])
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_rep_actions_keyboard(
    rep_id: int, is_active: bool, has_custom_price: bool = False
) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Suspend" if is_active else "🟢 Activate"
    price_text = "💰 Edit Custom Price" if has_custom_price else "💰 Set Custom Price"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=f"arep:toggle:{rep_id}")],
        [InlineKeyboardButton(text=price_text, callback_data=f"arep:set_price:{rep_id}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="arep:list")],
    ])


def admin_rep_charge_review(charge_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"arep:charge_approve:{charge_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"arep:charge_reject:{charge_id}"),
        ]
    ])


def admin_rep_settings_keyboard(ps: dict) -> InlineKeyboardMarkup:
    price = int(ps.get("rep_price_per_gb") or "5000")
    duration = ps.get("rep_config_duration_days") or "30"
    threshold = ps.get("rep_cashback_threshold_gb") or "40"
    percent = ps.get("rep_cashback_percent") or "5"
    min_cfg = ps.get("rep_min_config_gb") or "5"
    max_cfg = ps.get("rep_max_config_gb") or "30"
    min_charge = ps.get("rep_min_charge_gb") or "1"
    max_charge_raw = ps.get("rep_max_charge_gb") or "0"
    max_charge_label = f"{max_charge_raw} GB" if int(max_charge_raw) > 0 else "unlimited"
    currency = ps.get("currency_label") or "—"
    card = ps.get("rep_card_number") or "—"
    bank = ps.get("rep_bank_name") or "—"
    holder = ps.get("rep_card_holder_name") or "—"
    return InlineKeyboardMarkup(inline_keyboard=[
        # ── Pricing & config ──
        [InlineKeyboardButton(
            text=f"💰 Price/GB: {price:,} {currency}",
            callback_data="arep:set:rep_price_per_gb",
        )],
        [InlineKeyboardButton(
            text=f"📅 Config Duration: {duration} days",
            callback_data="arep:set:rep_config_duration_days",
        )],
        [InlineKeyboardButton(
            text=f"🎁 Cashback: {percent}% on {threshold}+ GB",
            callback_data="arep:set:rep_cashback_threshold_gb",
        )],
        [InlineKeyboardButton(
            text=f"📦 Config Range: {min_cfg}–{max_cfg} GB",
            callback_data="arep:set:rep_min_config_gb",
        )],
        # ── Charge transaction limits ──
        [InlineKeyboardButton(
            text=f"⬇️ Min Charge: {min_charge} GB",
            callback_data="arep:set:rep_min_charge_gb",
        )],
        [InlineKeyboardButton(
            text=f"⬆️ Max Charge: {max_charge_label}",
            callback_data="arep:set:rep_max_charge_gb",
        )],
        # ── Rep-only card payment ──
        [InlineKeyboardButton(
            text=f"💳 Rep Card: {card}",
            callback_data="arep:set:rep_card_number",
        )],
        [InlineKeyboardButton(
            text=f"🏦 Rep Bank: {bank}",
            callback_data="arep:set:rep_bank_name",
        )],
        [InlineKeyboardButton(
            text=f"👤 Rep Holder: {holder}",
            callback_data="arep:set:rep_card_holder_name",
        )],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="arep:list")],
    ])


def admin_payment_settings(ps: dict, nowpayments_key_set: bool = False) -> InlineKeyboardMarkup:
    card_on  = ps.get("card_payment_enabled", "1") == "1"
    stars_on = ps.get("stars_payment_enabled", "0") == "1"
    np_on    = ps.get("nowpayments_enabled", "0") == "1"
    card     = ps.get("card_number") or "—"
    bank     = ps.get("bank_name") or "—"
    holder   = ps.get("card_holder_name") or "—"
    currency = ps.get("currency_label") or "—"
    stars_rate = ps.get("stars_toman_per_star", "1000")
    usd_rate   = ps.get("usd_toman_rate", "600000")

    def _tog(label: str, on: bool) -> str:
        return f"{'🟢' if on else '🔴'} {label}: {'ON → Disable' if on else 'OFF → Enable'}"

    rows = [
        # ── Card ──
        [InlineKeyboardButton(text=_tog("Card", card_on), callback_data="apay:toggle_enabled")],
        [InlineKeyboardButton(text=f"💳 {card}", callback_data="apay:edit:card_number")],
        [InlineKeyboardButton(text=f"🏦 {bank}", callback_data="apay:edit:bank_name")],
        [InlineKeyboardButton(text=f"👤 {holder}", callback_data="apay:edit:card_holder_name")],
        [InlineKeyboardButton(text=f"💰 {currency}", callback_data="apay:edit:currency_label")],
        # ── Stars ──
        [InlineKeyboardButton(text=_tog("⭐ Stars", stars_on), callback_data="apay:toggle_stars")],
        [InlineKeyboardButton(text=f"⭐ Rate: {int(stars_rate):,} toman / star", callback_data="apay:edit:stars_toman_per_star")],
        # ── NOWPayments (crypto) ──
        [InlineKeyboardButton(
            text=_tog("💎 Crypto (NOWPayments)", np_on) + ("" if nowpayments_key_set else " ⚠️ no key"),
            callback_data="apay:toggle_nowpayments",
        )],
        [InlineKeyboardButton(text=f"💱 USD rate: {int(usd_rate):,} toman / $1", callback_data="apay:edit:usd_toman_rate")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:admin")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
