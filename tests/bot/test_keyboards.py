"""
tests.bot.test_keyboards
========================
Unit tests for all bot inline keyboard layouts, button text, and callback data contracts.
"""

from __future__ import annotations

import pytest
from telegram import InlineKeyboardMarkup

from bot.keyboards import (
    account_actions_keyboard,
    account_list_keyboard,
    back_to_accounts_keyboard,
    back_to_actions_keyboard,
    cancel_auth_keyboard,
    code_cancel_keyboard,
    create_account_actions_keyboard,
    delete_confirm_keyboard,
    main_menu_keyboard,
)


def test_main_menu_keyboard_structure() -> None:
    """Verify main menu has Add Account, List Accounts, and Help Guide buttons."""
    kb = main_menu_keyboard()
    assert isinstance(kb, InlineKeyboardMarkup)
    assert len(kb.inline_keyboard) == 3

    row0 = kb.inline_keyboard[0]
    assert len(row0) == 1
    assert "افزودن اکانت" in row0[0].text
    assert row0[0].callback_data == "add_account"

    row1 = kb.inline_keyboard[1]
    assert len(row1) == 1
    assert "مدیریت اکانت" in row1[0].text
    assert row1[0].callback_data == "list_accounts"

    row2 = kb.inline_keyboard[2]
    assert len(row2) == 1
    assert "راهنما" in row2[0].text
    assert row2[0].callback_data == "help_guide"


def test_cancel_auth_keyboard_structure() -> None:
    """Verify cancel_auth_keyboard displays clean cancel button."""
    kb = cancel_auth_keyboard()
    assert isinstance(kb, InlineKeyboardMarkup)
    assert len(kb.inline_keyboard) == 1
    btn = kb.inline_keyboard[0][0]
    assert "انصراف" in btn.text
    assert btn.callback_data == "cancel_auth"


def test_code_cancel_keyboard_structure() -> None:
    """Verify code_cancel_keyboard displays cancellation button for SMS code input."""
    kb = code_cancel_keyboard()
    assert isinstance(kb, InlineKeyboardMarkup)
    assert len(kb.inline_keyboard) == 1
    btn = kb.inline_keyboard[0][0]
    assert "انصراف" in btn.text
    assert btn.callback_data == "cancel_auth"


def test_account_list_keyboard_empty() -> None:
    """Verify empty account list prompts to add account."""
    kb = account_list_keyboard([])
    assert isinstance(kb, InlineKeyboardMarkup)
    assert len(kb.inline_keyboard) == 2
    btn = kb.inline_keyboard[0][0]
    assert "افزودن اکانت" in btn.text
    assert btn.callback_data == "add_account"


def test_account_list_keyboard_with_accounts() -> None:
    """Verify account list renders button per account plus Add Account and Back to Main Menu."""
    accounts = ["+15156723850", "+989999202880", "+14417071240"]
    kb = account_list_keyboard(accounts)
    assert isinstance(kb, InlineKeyboardMarkup)
    assert len(kb.inline_keyboard) == 5

    for i, phone in enumerate(accounts):
        btn = kb.inline_keyboard[i][0]
        assert phone in btn.text
        assert btn.callback_data == f"select_{phone}"

    add_btn = kb.inline_keyboard[3][0]
    assert "افزودن اکانت" in add_btn.text
    assert add_btn.callback_data == "add_account"

    back_btn = kb.inline_keyboard[4][0]
    assert "منوی اصلی" in back_btn.text
    assert back_btn.callback_data == "back_to_menu"


def test_account_actions_keyboard_13_buttons() -> None:
    """
    Verify account_actions_keyboard renders all 13 required action buttons
    with exact callback_data matching the specification.
    """
    phone = "+15156723850"
    kb = account_actions_keyboard(phone)
    assert isinstance(kb, InlineKeyboardMarkup)

    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(all_buttons) == 13

    expected_callbacks = [
        f"extract_7_{phone}",
        f"extract_8_{phone}",
        f"extract_9_{phone}",
        f"extract_7to9_{phone}",
        f"extract_10_{phone}",
        f"extract_11_{phone}",
        f"export_mutual_{phone}",
        f"check_contacts_{phone}",
        f"list_chats_{phone}",
        f"get_code_{phone}",
        f"delete_contacts_{phone}",
        f"logout_{phone}",
        "list_accounts",
    ]

    actual_callbacks = [btn.callback_data for btn in all_buttons]
    for cb in expected_callbacks:
        assert cb in actual_callbacks, f"Missing callback: {cb}"

    raw_list = create_account_actions_keyboard(phone)
    raw_buttons = [btn for row in raw_list for btn in row]
    assert len(raw_buttons) == 13


def test_delete_confirm_keyboard() -> None:
    """Verify delete confirmation presents Yes Delete and Cancel options."""
    phone = "+15156723850"
    kb = delete_confirm_keyboard(phone)
    assert isinstance(kb, InlineKeyboardMarkup)
    assert len(kb.inline_keyboard) == 2

    yes_btn = kb.inline_keyboard[0][0]
    assert "حذف شوند" in yes_btn.text
    assert yes_btn.callback_data == f"confirm_delete_{phone}"

    cancel_btn = kb.inline_keyboard[1][0]
    assert "انصراف" in cancel_btn.text
    assert cancel_btn.callback_data == f"select_{phone}"


def test_back_to_actions_keyboard() -> None:
    """Verify back_to_actions_keyboard targets select_{phone}."""
    phone = "+15156723850"
    kb = back_to_actions_keyboard(phone)
    assert isinstance(kb, InlineKeyboardMarkup)
    assert len(kb.inline_keyboard) == 1
    btn = kb.inline_keyboard[0][0]
    assert "بازگشت" in btn.text
    assert btn.callback_data == f"select_{phone}"


def test_back_to_accounts_keyboard() -> None:
    """Verify back_to_accounts_keyboard targets list_accounts."""
    kb = back_to_accounts_keyboard()
    assert isinstance(kb, InlineKeyboardMarkup)
    assert len(kb.inline_keyboard) == 1
    btn = kb.inline_keyboard[0][0]
    assert "لیست اکانت‌ها" in btn.text
    assert btn.callback_data == "list_accounts"
