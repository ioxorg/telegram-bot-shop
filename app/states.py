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
