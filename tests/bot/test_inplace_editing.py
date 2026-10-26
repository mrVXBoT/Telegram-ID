"""
tests.bot.test_inplace_editing
==============================
Unit tests verifying the single-message in-place editing flow:
- Safe deletion of user input messages (phone, SMS code, 2FA password, /start, /cancel)
- Tracking and in-place editing of prompt_message_id
- Fallback handling when messages are deleted or unmodifiable
- Bilingual error and result formatting
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest
from telegram import InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest, TelegramError

from bot.helpers import delete_user_message_safe, send_or_edit_prompt
from bot.handlers.auth_conversation import phone_handler, code_handler, password_handler
from bot.messages import format_bilingual_error, format_contacts_summary
from bot.states import CODE, WAITING_FOR_CODE, ACCOUNT_ACTIONS
from services.auth_service import AuthService, SignInResult
from services.session_manager import TelethonSessionManager


@pytest.mark.asyncio
async def test_delete_user_message_safe_success() -> None:
    """Verify delete_user_message_safe awaits message.delete and returns True."""
    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.delete = AsyncMock()

    result = await delete_user_message_safe(update)
    assert result is True
    update.message.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_user_message_safe_handles_exception() -> None:
    """Verify delete_user_message_safe suppresses TelegramError and returns False."""
    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.delete = AsyncMock(side_effect=BadRequest("Message can't be deleted"))

    result = await delete_user_message_safe(update)
    assert result is False


@pytest.mark.asyncio
async def test_send_or_edit_prompt_callback_query() -> None:
    """Verify send_or_edit_prompt edits message in-place for callback queries."""
    update = MagicMock(spec=Update)
    update.callback_query = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    mock_msg = MagicMock(spec=Message)
    mock_msg.message_id = 777
    update.callback_query.edit_message_text.return_value = mock_msg
    update.message = None

    context = MagicMock()
    context.user_data = {}

    res = await send_or_edit_prompt(update, context, text="Updated Menu Text")
    assert res == mock_msg
    assert context.user_data["prompt_message_id"] == 777
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_or_edit_prompt_user_message_with_existing_prompt() -> None:
    """Verify user message is deleted and tracked prompt is edited in-place."""
    update = MagicMock(spec=Update)
    update.callback_query = None
    update.message = MagicMock(spec=Message)
    update.message.delete = AsyncMock()
    update.effective_chat.id = 9999

    context = MagicMock()
    context.user_data = {"prompt_message_id": 555}
    context.bot.edit_message_text = AsyncMock()
    mock_edited = MagicMock(spec=Message)
    context.bot.edit_message_text.return_value = mock_edited

    res = await send_or_edit_prompt(update, context, text="Next Step Prompt")
    assert res == mock_edited
    update.message.delete.assert_awaited_once()
    context.bot.edit_message_text.assert_awaited_once_with(
        chat_id=9999,
        message_id=555,
        text="Next Step Prompt",
        reply_markup=None,
    )


@pytest.mark.asyncio
async def test_phone_handler_inplace_editing_and_deletion() -> None:
    """Verify phone_handler deletes user's phone message and edits prompt in-place."""
    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_sm.is_authorized = AsyncMock(return_value=False)
    mock_sm.get_client = AsyncMock()
    mock_auth = MagicMock(spec=AuthService)
    mock_auth.send_code = AsyncMock(return_value="hash_xyz")

    update = MagicMock(spec=Update)
    update.callback_query = None
    update.message = MagicMock(spec=Message)
    update.message.text = "+989123456789"
    update.message.delete = AsyncMock()
    update.effective_user.id = 123456
    update.effective_chat.id = 123456

    context = MagicMock()
    context.bot_data = {
        "session_manager": mock_sm,
        "auth_service": mock_auth,
        "pending_auth": {},
    }
    context.user_data = {"prompt_message_id": 100}
    context.bot.edit_message_text = AsyncMock()

    state = await phone_handler(update, context)
    assert state == CODE
    # User's phone number message must have been deleted
    update.message.delete.assert_awaited_once()
    # The existing prompt message must have been edited in-place
    context.bot.edit_message_text.assert_awaited_once()
    edit_kwargs = context.bot.edit_message_text.call_args[1]
    assert edit_kwargs["chat_id"] == 123456
    assert edit_kwargs["message_id"] == 100
    assert "+989123456789" in edit_kwargs["text"]


@pytest.mark.asyncio
async def test_code_handler_inplace_editing_and_deletion() -> None:
    """Verify code_handler deletes secret SMS code message and completes login in-place."""
    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_auth = MagicMock(spec=AuthService)
    mock_auth.sign_in = AsyncMock(
        return_value=SignInResult(status="success", phone="+989123456789", user_id=123)
    )

    update = MagicMock(spec=Update)
    update.callback_query = None
    update.message = MagicMock(spec=Message)
    update.message.text = "98765"
    update.message.delete = AsyncMock()
    update.effective_user.id = 123456
    update.effective_chat.id = 123456

    context = MagicMock()
    context.bot_data = {
        "session_manager": mock_sm,
        "auth_service": mock_auth,
        "account_repo": MagicMock(add_account=AsyncMock()),
        "pending_auth": {
            123456: {
                "phone": "+989123456789",
                "client": MagicMock(),
                "phone_code_hash": "hash_xyz",
            }
        },
    }
    context.user_data = {"prompt_message_id": 100}
    context.bot.edit_message_text = AsyncMock()

    state = await code_handler(update, context)
    assert state == ACCOUNT_ACTIONS
    # User's SMS code message must have been deleted
    update.message.delete.assert_awaited_once()
    # The prompt message must have been edited in-place with success
    context.bot.edit_message_text.assert_awaited_once()
    edit_kwargs = context.bot.edit_message_text.call_args[1]
    assert edit_kwargs["chat_id"] == 123456
    assert edit_kwargs["message_id"] == 100
    assert "+989123456789" in edit_kwargs["text"]


@pytest.mark.asyncio
async def test_bilingual_error_formatting() -> None:
    """Verify format_bilingual_error includes Persian and English descriptions."""
    msg = format_bilingual_error("حذف مخاطبین", "Contact deletion", "FloodWait: 30 seconds")
    assert "خطا در حذف مخاطبین" in msg
    assert "Error: Contact deletion" in msg
    assert "FloodWait: 30 seconds" in msg
    assert "لطفاً مجدداً تلاش نمایید" in msg
    assert "Please try again." in msg


def test_bilingual_contacts_summary() -> None:
    """Verify format_contacts_summary contains both Persian and English descriptions."""
    summary = {
        "total": 50,
        "mutual": 20,
        "breakdown": {7: 10, 8: 15, 9: 25, 10: 0, 11: 0},
        "samples": [],
    }
    text = format_contacts_summary("+989123456789", summary)
    assert "آمار مخاطبین | Contacts Overview" in text
    assert "کل مخاطبین | Total contacts: 50" in text
    assert "مخاطبین دوطرفه | Mutual contacts: 20" in text
    assert "7 رقمی | Contacts with 7 digit IDs: 10" in text
