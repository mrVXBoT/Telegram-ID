"""
tests.bot.test_conversation_flow
================================
Mocked integration tests for ConversationHandler states, transitions,
phone validation, SMS code, 2FA password, and universal /start & /cancel re-entry.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest
from telegram.ext import ConversationHandler

from bot.handlers.auth_conversation import (
    add_account_callback,
    code_handler,
    password_handler,
    phone_handler,
)
from bot.handlers.start import cancel, cancel_auth, start
from bot.states import ACCOUNT_ACTIONS, CODE, PHONE, WAITING_FOR_CODE
from database.connection import DatabaseConnection
from database.repository import AccountRepository, UserRepository
from services.auth_service import AuthService, SignInResult
from services.session_manager import TelethonSessionManager


def make_mock_context(
    bot_data: dict | None = None, user_data: dict | None = None
) -> MagicMock:
    """Create a mock ContextTypes.DEFAULT_TYPE with isolated bot_data and user_data."""
    context = MagicMock()
    context.bot_data = bot_data if bot_data is not None else {}
    context.user_data = user_data if user_data is not None else {}
    context.bot.send_message = AsyncMock()
    context.bot.send_document = AsyncMock()
    return context


def make_message_update(
    text: str, user_id: int = 123456, chat_id: int = 123456
) -> MagicMock:
    """Create a mock message Update."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.date = "2026-10-25T22:00:00Z"
    update.message.reply_text = AsyncMock()
    update.callback_query = None
    return update


def make_callback_update(
    callback_data: str, user_id: int = 123456, chat_id: int = 123456
) -> MagicMock:
    """Create a mock callback_query Update."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message = None

    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update.callback_query = query
    return update


@pytest.mark.asyncio
async def test_start_command_resets_pending_and_sends_welcome(db: DatabaseConnection) -> None:
    """Verify /start cleans up pending auth, creates user, sends welcome, ends conversation."""
    user_repo = UserRepository(db)

    pending_client = MagicMock()
    pending_client.disconnect = AsyncMock()

    context = make_mock_context(
        bot_data={
            "user_repo": user_repo,
            "pending_auth": {123456: {"client": pending_client, "phone": "+15156723850"}},
        }
    )
    update = make_message_update(text="/start", user_id=123456)

    res = await start(update, context)
    assert res == ConversationHandler.END

    # Pending auth client must be disconnected and cleared
    pending_client.disconnect.assert_awaited_once()
    assert 123456 not in context.bot_data["pending_auth"]

    # User record must be persisted in database
    user = await user_repo.get_user(123456)
    assert user is not None
    assert user.user_id == 123456

    # Welcome message must be sent
    context.bot.send_message.assert_awaited_once()
    sent_args = context.bot.send_message.call_args[1]
    assert "Welcome to Telegram Account Manager Bot" in sent_args["text"]


@pytest.mark.asyncio
async def test_cancel_command_cleans_up_and_returns_end() -> None:
    """Verify /cancel cleans up pending client and returns ConversationHandler.END."""
    pending_client = MagicMock()
    pending_client.disconnect = AsyncMock()

    context = make_mock_context(
        bot_data={
            "pending_auth": {123456: {"client": pending_client, "phone": "+15156723850"}},
        }
    )
    update = make_message_update(text="/cancel", user_id=123456)

    res = await cancel(update, context)
    assert res == ConversationHandler.END
    pending_client.disconnect.assert_awaited_once()
    assert 123456 not in context.bot_data["pending_auth"]
    update.message.reply_text.assert_awaited_once()
    assert "Operation cancelled" in update.message.reply_text.call_args[1]["text"]


@pytest.mark.asyncio
async def test_cancel_auth_callback_cleans_up() -> None:
    """Verify cancel_auth callback edits message to cancelled and ends conversation."""
    pending_client = MagicMock()
    pending_client.disconnect = AsyncMock()

    context = make_mock_context(
        bot_data={
            "pending_auth": {123456: {"client": pending_client, "phone": "+15156723850"}},
        }
    )
    update = make_callback_update(callback_data="cancel_auth", user_id=123456)

    res = await cancel_auth(update, context)
    assert res == ConversationHandler.END
    pending_client.disconnect.assert_awaited_once()
    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "Operation cancelled" in update.callback_query.edit_message_text.call_args[1]["text"]


@pytest.mark.asyncio
async def test_add_account_callback_transitions_to_phone() -> None:
    """Verify clicking Add Account prompts for phone number and enters PHONE state."""
    context = make_mock_context()
    update = make_callback_update(callback_data="add_account", user_id=123456)

    res = await add_account_callback(update, context)
    assert res == PHONE
    update.callback_query.edit_message_text.assert_awaited_once()
    args = update.callback_query.edit_message_text.call_args[1]
    assert "Please send your phone number" in args["text"]


@pytest.mark.asyncio
async def test_phone_handler_invalid_phone_stays_in_phone() -> None:
    """Verify submitting an invalid phone number warns the user and stays in PHONE state."""
    context = make_mock_context()
    update = make_message_update(text="not-a-phone", user_id=123456)

    res = await phone_handler(update, context)
    assert res == PHONE
    update.message.reply_text.assert_awaited_once()
    assert "Invalid phone number format" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_phone_handler_already_authorized_adds_account_and_ends(db: DatabaseConnection) -> None:
    """Verify submitting an already authorized phone adds account and presents actions."""
    account_repo = AccountRepository(db)

    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_sm.is_authorized = AsyncMock(return_value=True)

    context = make_mock_context(
        bot_data={"session_manager": mock_sm, "account_repo": account_repo}
    )
    update = make_message_update(text="+15156723850", user_id=123456)

    res = await phone_handler(update, context)
    assert res == ConversationHandler.END

    accounts = await account_repo.get_user_accounts(123456)
    assert len(accounts) == 1
    assert accounts[0].phone_number == "+15156723850"

    update.message.reply_text.assert_awaited_once()
    call_args = update.message.reply_text.call_args[1]
    assert "already authorized" in call_args["text"]


@pytest.mark.asyncio
async def test_phone_handler_valid_sends_code_transitions_to_code() -> None:
    """Verify submitting an unauthorized valid phone requests code and transitions to CODE state."""
    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_sm.is_authorized = AsyncMock(return_value=False)
    mock_client = MagicMock()
    mock_sm.get_client = AsyncMock(return_value=mock_client)

    mock_auth = MagicMock(spec=AuthService)
    mock_auth.send_code = AsyncMock(return_value="mock_hash_456")

    context = make_mock_context(
        bot_data={"session_manager": mock_sm, "auth_service": mock_auth}
    )
    update = make_message_update(text="+15156723850", user_id=123456)

    res = await phone_handler(update, context)
    assert res == CODE

    mock_auth.send_code.assert_awaited_once_with("+15156723850")
    pending = context.bot_data["pending_auth"][123456]
    assert pending["phone"] == "+15156723850"
    assert pending["phone_code_hash"] == "mock_hash_456"

    update.message.reply_text.assert_awaited_once()
    call_args = update.message.reply_text.call_args[1]
    assert "Verification code sent to +15156723850" in call_args["text"]


@pytest.mark.asyncio
async def test_code_handler_success_transitions_to_account_actions(db: DatabaseConnection) -> None:
    """Verify submitting correct verification code completes login and enters ACCOUNT_ACTIONS."""
    account_repo = AccountRepository(db)

    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_auth = MagicMock(spec=AuthService)
    mock_auth.sign_in = AsyncMock(
        return_value=SignInResult(status="success", phone="+15156723850", user_id=999)
    )

    context = make_mock_context(
        bot_data={
            "session_manager": mock_sm,
            "auth_service": mock_auth,
            "account_repo": account_repo,
            "pending_auth": {
                123456: {
                    "phone": "+15156723850",
                    "client": MagicMock(),
                    "phone_code_hash": "hash123",
                }
            },
        }
    )
    update = make_message_update(text="12345", user_id=123456)

    res = await code_handler(update, context)
    assert res == ACCOUNT_ACTIONS

    # Pending auth must be cleaned up
    assert 123456 not in context.bot_data["pending_auth"]
    assert context.user_data["current_phone"] == "+15156723850"

    # Account must be persisted in database
    accounts = await account_repo.get_user_accounts(123456)
    assert len(accounts) == 1
    assert accounts[0].phone_number == "+15156723850"

    update.message.reply_text.assert_awaited_once()
    assert "Successfully logged in" in update.message.reply_text.call_args[1]["text"]


@pytest.mark.asyncio
async def test_code_handler_2fa_required_transitions_to_waiting_for_code() -> None:
    """Verify when 2FA password is required, transitions to WAITING_FOR_CODE state."""
    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_auth = MagicMock(spec=AuthService)
    mock_auth.sign_in = AsyncMock(
        return_value=SignInResult(status="2fa_required", phone="+15156723850")
    )

    context = make_mock_context(
        bot_data={
            "session_manager": mock_sm,
            "auth_service": mock_auth,
            "pending_auth": {
                123456: {
                    "phone": "+15156723850",
                    "client": MagicMock(),
                    "phone_code_hash": "hash123",
                }
            },
        }
    )
    update = make_message_update(text="12345", user_id=123456)

    res = await code_handler(update, context)
    assert res == WAITING_FOR_CODE
    assert context.user_data.get("awaiting_2fa") is True
    update.message.reply_text.assert_awaited_once()
    assert "two-factor authentication" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_code_handler_invalid_code_stays_in_code_state() -> None:
    """Verify invalid code informs user and stays in CODE state."""
    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_auth = MagicMock(spec=AuthService)
    mock_auth.sign_in = AsyncMock(
        return_value=SignInResult(status="invalid_code", phone="+15156723850")
    )

    context = make_mock_context(
        bot_data={
            "session_manager": mock_sm,
            "auth_service": mock_auth,
            "pending_auth": {
                123456: {
                    "phone": "+15156723850",
                    "client": MagicMock(),
                    "phone_code_hash": "hash123",
                }
            },
        }
    )
    update = make_message_update(text="wrong", user_id=123456)

    res = await code_handler(update, context)
    assert res == CODE
    update.message.reply_text.assert_awaited_once()
    assert "Invalid code" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_password_handler_success_transitions_to_actions(db: DatabaseConnection) -> None:
    """Verify correct 2FA password completes login and enters ACCOUNT_ACTIONS."""
    account_repo = AccountRepository(db)

    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_auth = MagicMock(spec=AuthService)
    mock_auth.sign_in_2fa = AsyncMock(
        return_value=SignInResult(status="success", phone="+15156723850", user_id=999)
    )

    context = make_mock_context(
        bot_data={
            "session_manager": mock_sm,
            "auth_service": mock_auth,
            "account_repo": account_repo,
            "pending_auth": {
                123456: {
                    "phone": "+15156723850",
                    "client": MagicMock(),
                }
            },
        }
    )
    update = make_message_update(text="mypassword123", user_id=123456)

    res = await password_handler(update, context)
    assert res == ACCOUNT_ACTIONS
    assert 123456 not in context.bot_data["pending_auth"]

    accounts = await account_repo.get_user_accounts(123456)
    assert len(accounts) == 1
    assert accounts[0].phone_number == "+15156723850"

    update.message.reply_text.assert_awaited_once()
    assert "Successfully logged in" in update.message.reply_text.call_args[1]["text"]


@pytest.mark.asyncio
async def test_password_handler_invalid_password_stays_in_waiting() -> None:
    """Verify incorrect 2FA password prompts retry in WAITING_FOR_CODE state."""
    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_auth = MagicMock(spec=AuthService)
    mock_auth.sign_in_2fa = AsyncMock(
        return_value=SignInResult(status="invalid_password", phone="+15156723850")
    )

    context = make_mock_context(
        bot_data={
            "session_manager": mock_sm,
            "auth_service": mock_auth,
            "pending_auth": {
                123456: {
                    "phone": "+15156723850",
                    "client": MagicMock(),
                }
            },
        }
    )
    update = make_message_update(text="badpass", user_id=123456)

    res = await password_handler(update, context)
    assert res == WAITING_FOR_CODE
    update.message.reply_text.assert_awaited_once()
    assert "Invalid 2FA password" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_session_expired_when_pending_missing() -> None:
    """Verify expired/missing pending auth returns END with prompt to restart."""
    context = make_mock_context(bot_data={"pending_auth": {}})
    update = make_message_update(text="12345", user_id=123456)

    res = await code_handler(update, context)
    assert res == ConversationHandler.END
    update.message.reply_text.assert_awaited_once()
    assert "Session expired" in update.message.reply_text.call_args[0][0]
