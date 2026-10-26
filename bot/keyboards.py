"""
bot.keyboards
=============
InlineKeyboardMarkup builders for bot navigation, account operations, and confirmations.
Designed following Telegram UX guidelines: concise, punchy labels that never truncate on mobile screens.
"""

from __future__ import annotations

from typing import Iterable, List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.messages import (
    BACK_TO_ACTIONS_TEXT,
    CANCEL_DELETE,
    CANCEL_PERSIAN_ENGLISH,
    CANCEL_RED_PERSIAN_ENGLISH,
    YES_DELETE_ALL,
)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Create the initial welcome main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("➕ افزودن اکانت", callback_data="add_account")],
        [InlineKeyboardButton("📱 مدیریت اکانت‌ها", callback_data="list_accounts")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help_guide")],
    ]
    return InlineKeyboardMarkup(keyboard)


def help_guide_keyboard() -> InlineKeyboardMarkup:
    """Create back button for help guide view."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_menu")]
    ])


def cancel_auth_keyboard() -> InlineKeyboardMarkup:
    """Create cancellation keyboard for phone input step."""
    keyboard = [
        [InlineKeyboardButton("❌ انصراف", callback_data="cancel_auth")]
    ]
    return InlineKeyboardMarkup(keyboard)


def code_cancel_keyboard() -> InlineKeyboardMarkup:
    """Create cancellation keyboard for SMS/verification code input step."""
    keyboard = [
        [InlineKeyboardButton("❌ انصراف", callback_data="cancel_auth")]
    ]
    return InlineKeyboardMarkup(keyboard)


def account_list_keyboard(accounts: Iterable[str]) -> InlineKeyboardMarkup:
    """
    Create account list selection keyboard.

    If accounts exist, generates a select button for each phone number,
    followed by 'Add Account' and 'Back to Menu'. If no accounts exist,
    presents 'Add Account' and 'Back to Menu'.
    """
    acc_list = list(accounts)
    if not acc_list:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ افزودن اکانت", callback_data="add_account")],
            [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_menu")],
        ])

    keyboard: List[List[InlineKeyboardButton]] = []
    for phone in acc_list:
        keyboard.append(
            [InlineKeyboardButton(f"📱 {phone}", callback_data=f"select_{phone}")]
        )
    keyboard.append(
        [InlineKeyboardButton("➕ افزودن اکانت", callback_data="add_account")]
    )
    keyboard.append(
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_menu")]
    )
    return InlineKeyboardMarkup(keyboard)


def create_account_actions_keyboard(phone: str) -> List[List[InlineKeyboardButton]]:
    """
    Construct an organized, modern multi-column keyboard for account actions.
    Presents digit length filters, mutual contacts, chats, codes, and session controls.
    All labels are concise (≤15 characters) so they never truncate with '...' on mobile screens.
    """
    return [
        [
            InlineKeyboardButton("🎯 ۷ رقمی", callback_data=f"extract_7_{phone}"),
            InlineKeyboardButton("🎯 ۸ رقمی", callback_data=f"extract_8_{phone}"),
        ],
        [
            InlineKeyboardButton("🎯 ۹ رقمی", callback_data=f"extract_9_{phone}"),
            InlineKeyboardButton("📦 ۷ تا ۹ رقمی", callback_data=f"extract_7to9_{phone}"),
        ],
        [
            InlineKeyboardButton("🎯 ۱۰ رقمی", callback_data=f"extract_10_{phone}"),
            InlineKeyboardButton("🎯 ۱۱ رقمی", callback_data=f"extract_11_{phone}"),
        ],
        [
            InlineKeyboardButton("👥 مخاطب دوطرفه", callback_data=f"export_mutual_{phone}"),
            InlineKeyboardButton("📊 آمار مخاطبین", callback_data=f"check_contacts_{phone}"),
        ],
        [
            InlineKeyboardButton("💬 چت‌ها و گروه‌ها", callback_data=f"list_chats_{phone}"),
            InlineKeyboardButton("🔑 آخرین کد ورود", callback_data=f"get_code_{phone}"),
        ],
        [
            InlineKeyboardButton("🗑️ حذف مخاطبین", callback_data=f"delete_contacts_{phone}"),
            InlineKeyboardButton("🚪 خروج از اکانت", callback_data=f"logout_{phone}"),
        ],
        [
            InlineKeyboardButton("🔙 لیست اکانت‌ها", callback_data="list_accounts"),
        ],
    ]


def account_actions_keyboard(phone: str) -> InlineKeyboardMarkup:
    """Create the full 13-button account actions InlineKeyboardMarkup."""
    return InlineKeyboardMarkup(create_account_actions_keyboard(phone))


def delete_confirm_keyboard(phone: str) -> InlineKeyboardMarkup:
    """Create two-step confirmation keyboard for contact deletion."""
    keyboard = [
        [InlineKeyboardButton(YES_DELETE_ALL, callback_data=f"confirm_delete_{phone}")],
        [InlineKeyboardButton(CANCEL_DELETE, callback_data=f"select_{phone}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def back_to_actions_keyboard(phone: str) -> InlineKeyboardMarkup:
    """Create sub-menu back button returning to account actions."""
    keyboard = [
        [InlineKeyboardButton(BACK_TO_ACTIONS_TEXT, callback_data=f"select_{phone}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def back_to_accounts_keyboard() -> InlineKeyboardMarkup:
    """Create back button returning to account list."""
    keyboard = [
        [InlineKeyboardButton("🔙 لیست اکانت‌ها", callback_data="list_accounts")]
    ]
    return InlineKeyboardMarkup(keyboard)
