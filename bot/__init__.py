"""
bot
===
Modular python-telegram-bot UI, application lifecycle, and handler framework
for Telegram Account Manager & Contact Extractor.
"""

from __future__ import annotations

from bot.application import build_application, create_conversation_handler
from bot.keyboards import (
    account_actions_keyboard,
    account_list_keyboard,
    back_to_accounts_keyboard,
    back_to_actions_keyboard,
    cancel_auth_keyboard,
    code_cancel_keyboard,
    delete_confirm_keyboard,
    main_menu_keyboard,
)
from bot.messages import (
    ADD_ACCOUNT_PROMPT,
    ALREADY_AUTHORIZED_TEXT,
    DELETE_WARNING_TEXT,
    INVALID_CODE_TEXT,
    INVALID_PHONE_TEXT,
    LOGIN_SUCCESS_TEXT,
    OPERATION_CANCELLED_TEXT,
    TWO_FA_PROMPT,
    WELCOME_TEXT,
)
from bot.states import ACCOUNT_ACTIONS, CODE, PHONE, WAITING_FOR_CODE

__all__ = [
    "build_application",
    "create_conversation_handler",
    "PHONE",
    "CODE",
    "WAITING_FOR_CODE",
    "ACCOUNT_ACTIONS",
    "main_menu_keyboard",
    "cancel_auth_keyboard",
    "code_cancel_keyboard",
    "account_list_keyboard",
    "account_actions_keyboard",
    "delete_confirm_keyboard",
    "back_to_actions_keyboard",
    "back_to_accounts_keyboard",
    "WELCOME_TEXT",
    "ADD_ACCOUNT_PROMPT",
    "ALREADY_AUTHORIZED_TEXT",
    "LOGIN_SUCCESS_TEXT",
    "TWO_FA_PROMPT",
    "INVALID_CODE_TEXT",
    "INVALID_PHONE_TEXT",
    "OPERATION_CANCELLED_TEXT",
    "DELETE_WARNING_TEXT",
]
