from aiogram.fsm.state import State, StatesGroup


class PurchaseStates(StatesGroup):
    waiting_for_config_name = State()
    waiting_for_receipt = State()


class AdminStates(StatesGroup):
    awaiting_reject_reason = State()


class AdminPlanStates(StatesGroup):
    waiting_for_new_plan = State()
    waiting_for_edit_plan = State()


class AdminSettingsStates(StatesGroup):
    editing_card_number = State()
    editing_bank_name = State()
    editing_card_holder = State()
    editing_currency = State()
    editing_stars_rate = State()
    editing_usd_rate = State()


class VerificationStates(StatesGroup):
    waiting_for_phone = State()


class AdminForceJoinStates(StatesGroup):
    waiting_for_channel = State()


class SalesRepStates(StatesGroup):
    waiting_for_charge_amount = State()
    waiting_for_charge_receipt = State()
    waiting_for_config_name = State()
    waiting_for_config_gb = State()


class AdminRepStates(StatesGroup):
    waiting_for_rep_telegram_id = State()
    awaiting_charge_reject_reason = State()
    editing_rep_setting = State()
    setting_rep_custom_price = State()


class BroadcastStates(StatesGroup):
    waiting_for_message = State()
    confirming = State()
