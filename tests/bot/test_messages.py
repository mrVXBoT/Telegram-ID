"""
tests.bot.test_messages
=======================
Unit tests for message templates, bilingual strings, and formatting helpers.
"""

from __future__ import annotations

import pytest

from bot.messages import (
    ADD_ACCOUNT_PROMPT,
    INVALID_CODE_TEXT,
    INVALID_PHONE_TEXT,
    NO_ACCOUNTS_TEXT,
    OPERATION_CANCELLED_TEXT,
    TWO_FA_PROMPT,
    WELCOME_TEXT,
    format_account_actions,
    format_accounts_list,
    format_already_authorized,
    format_contacts_summary,
    format_creator_chats,
    format_delete_progress,
    format_delete_progress_start,
    format_delete_result,
    format_delete_warning,
    format_latest_code,
    format_login_success,
    format_logout_success,
    format_no_code_found,
    format_no_contacts_to_delete,
    format_verification_prompt,
    format_welcome,
)
from services.chat_service import ChatInfo
from utils.vcf import ContactInfo


def test_welcome_message() -> None:
    """Verify welcome message string contains core introductory text."""
    welcome = format_welcome()
    assert "Telegram Account Manager" in welcome
    assert "extract contacts" in welcome
    assert welcome == WELCOME_TEXT


def test_verification_prompt() -> None:
    """Verify phone number is interpolated into SMS prompt."""
    phone = "+15156723850"
    msg = format_verification_prompt(phone)
    assert phone in msg
    assert "Verification code sent to" in msg
    assert "/cancel" in msg


def test_already_authorized() -> None:
    """Verify format_already_authorized includes phone number."""
    phone = "+15156723850"
    msg = format_already_authorized(phone)
    assert phone in msg
    assert "already authorized" in msg


def test_login_success() -> None:
    """Verify format_login_success includes phone number."""
    phone = "+15156723850"
    msg = format_login_success(phone)
    assert phone in msg
    assert "Successfully logged in" in msg


def test_account_actions_formatting() -> None:
    """Verify account actions prompt formatting."""
    phone = "+15156723850"
    msg_initial = format_account_actions(phone, next_action=False)
    assert phone in msg_initial
    assert "What would you like to do?" in msg_initial

    msg_next = format_account_actions(phone, next_action=True)
    assert phone in msg_next
    assert "What would you like to do next?" in msg_next


def test_accounts_list_formatting() -> None:
    """Verify account list formatting handles empty and populated lists."""
    empty_msg = format_accounts_list([])
    assert empty_msg == NO_ACCOUNTS_TEXT

    phones = ["+15156723850", "+989999202880"]
    populated_msg = format_accounts_list(phones)
    assert "Your accounts:" in populated_msg
    assert "📱 +15156723850" in populated_msg
    assert "📱 +989999202880" in populated_msg


def test_logout_success() -> None:
    """Verify logout message contains phone."""
    phone = "+15156723850"
    msg = format_logout_success(phone)
    assert phone in msg
    assert "Successfully logged out" in msg


def test_delete_warning_bilingual() -> None:
    """Verify delete warning contains bilingual text and contact count."""
    phone = "+15156723850"
    total = 250
    msg = format_delete_warning(phone, total)
    assert phone in msg
    assert "250" in msg
    assert "هشدار" in msg
    assert "Warning" in msg
    assert "آیا مطمئن هستید؟" in msg
    assert "Are you sure?" in msg


def test_no_contacts_to_delete() -> None:
    """Verify notice when no contacts exist to delete."""
    phone = "+15156723850"
    msg = format_no_contacts_to_delete(phone)
    assert phone in msg
    assert "هیچ مخاطبی برای حذف پیدا نشد" in msg
    assert "No contacts found to delete" in msg


def test_delete_progress_start() -> None:
    """Verify initial deletion progress message."""
    phone = "+15156723850"
    msg = format_delete_progress_start(phone, 120)
    assert phone in msg
    assert "120" in msg
    assert "لطفاً منتظر بمانید" in msg


def test_delete_progress() -> None:
    """Verify dynamic percentage progress formatting."""
    phone = "+15156723850"
    msg = format_delete_progress(phone, 50, 60, 120)
    assert phone in msg
    assert "50%" in msg
    assert "60/120" in msg
    assert "Progress:" in msg
    assert "پیشرفت:" in msg


def test_delete_result() -> None:
    """Verify final delete summary report formatting."""
    phone = "+15156723850"
    msg = format_delete_result(phone, success_count=100, failed_count=2, total_contacts=102)
    assert phone in msg
    assert "عملیات حذف مخاطبین تکمیل شد" in msg
    assert "Contact deletion completed" in msg
    assert "حذف شده: 100" in msg
    assert "Deleted: 100" in msg
    assert "ناموفق: 2" in msg
    assert "Failed: 2" in msg
    assert "کل: 102" in msg
    assert "Total: 102" in msg


def test_contacts_summary_formatting() -> None:
    """Verify contacts summary report with total, mutual, breakdown, and samples."""
    phone = "+15156723850"
    summary = {
        "total": 30,
        "mutual": 12,
        "breakdown": {7: 5, 8: 10, 9: 15, 10: 0, 11: 0},
        "samples": [
            ContactInfo(id=1234567, first_name="Alice", last_name="Smith"),
            ContactInfo(id=7654321, first_name="Bob"),
        ],
    }
    text = format_contacts_summary(phone, summary)
    assert "Total contacts: 30" in text
    assert "Mutual contacts: 12" in text
    assert "Contacts with 7 digit IDs: 5" in text
    assert "Contacts with 8 digit IDs: 10" in text
    assert "Contacts with 9 digit IDs: 15" in text
    assert "ID: 1234567, Name: Alice Smith" in text
    assert "ID: 7654321, Name: Bob" in text


def test_creator_chats_formatting() -> None:
    """Verify formatted creator chats listing separates channels, groups, and regular chats."""
    phone = "+15156723850"
    chats = [
        ChatInfo(
            id=1001,
            title="My Channel",
            type="channel",
            link="https://t.me/mychannel",
            creation_date="2023-01-15",
            creation_year=2023,
            history_visibility="Visible",
        ),
        ChatInfo(
            id=1002,
            title="My Supergroup",
            type="supergroup",
            link="https://t.me/mygroup",
            creation_date="2024-02-20",
            creation_year=2024,
            history_visibility="Hidden",
        ),
    ]
    text = format_creator_chats(phone, chats)
    assert "Account: +15156723850" in text
    assert "کانال‌های شما / Your Channels" in text
    assert "『 My Channel 』" in text
    assert "Link: https://t.me/mychannel" in text
    assert "تاریخ ساخت: 2023-01-15 (سال 2023)" in text
    assert "تاریخچه: 👁️ Visible / قابل مشاهده" in text

    assert "گروه‌های شما / Your Groups" in text
    assert "『 My Supergroup 』" in text
    assert "Link: https://t.me/mygroup" in text
    assert "تاریخچه: 🔒 Hidden / مخفی" in text


def test_creator_chats_formatting_empty() -> None:
    """Verify empty creator chats list returns notice."""
    phone = "+15156723850"
    text = format_creator_chats(phone, [])
    assert "No creator chats found." in text


def test_latest_code_formatting() -> None:
    """Verify latest code formatting."""
    phone = "+15156723850"
    code_text = "Login code: 49281. Do not give this code to anyone."
    msg = format_latest_code(phone, code_text)
    assert phone in msg
    assert "49281" in msg

    no_code = format_no_code_found(phone)
    assert phone in no_code
    assert "No recent code messages found" in no_code
