"""
tests.bot.test_adversarial_m4_flow
==================================
Adversarial stress-testing suite for Milestone 4 (Bot Conversation Flow & Lifecycle):
1. Re-entry robustness (/start and /cancel during PHONE, CODE, 2FA, invalid input).
2. 2FA challenge flow (SessionPasswordNeededError, incorrect 2FA retry, cancel mid-2FA, rate limits).
3. Unauthorized or expired session handling (missing session file, revoked auth mid-flight).
4. Button router dispatch edge cases (unknown callbacks, malformed data, concurrent clicks).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from telegram.ext import ConversationHandler

from bot.application import build_application, create_conversation_handler
from bot.handlers import (
    add_account_callback,
    back_to_menu,
    button_router,
    cancel,
    cancel_auth,
    check_contacts_callback,
    code_handler,
    confirm_delete_callback,
    default_message_handler,
    delete_contacts_callback,
    error_handler,
    export_mutual_callback,
    extract_contacts_callback,
    get_code_callback,
    list_accounts_callback,
    list_chats_callback,
    logout_account_callback,
    password_handler,
    phone_handler,
    select_account_callback,
    start,
)
from bot.messages import (
    ACCOUNT_NOT_FOUND_TEXT,
    DEFAULT_FALLBACK_TEXT,
    ERROR_GENERIC_TEXT,
    ERROR_SUPPORT_TEXT,
    INVALID_CODE_TEXT,
    INVALID_PASSWORD_TEXT,
    INVALID_PHONE_TEXT,
    OPERATION_CANCELLED_TEXT,
    SESSION_EXPIRED_RESTART_TEXT,
    SESSION_EXPIRED_TEXT,
    TWO_FA_PROMPT,
)
from bot.states import ACCOUNT_ACTIONS, CODE, PHONE, WAITING_FOR_CODE
from database.connection import DatabaseConnection
from database.repository import AccountRepository, OperationLogRepository, UserRepository
from services.auth_service import AuthService, SignInResult
from services.chat_service import ChatInfo, ChatService
from services.contact_service import ContactService, DeleteResult
from services.session_manager import TelethonSessionManager
from utils.vcf import ContactInfo


# ============================================================================
# Helpers
# ============================================================================

def make_ctx(bot_data: dict | None = None, user_data: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = bot_data if bot_data is not None else {}
    ctx.user_data = user_data if user_data is not None else {}
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_document = AsyncMock()
    return ctx


def make_msg_update(text: str | None = None, user_id: int = 123456, chat_id: int | None = None) -> MagicMock:
    resolved_chat_id = chat_id if chat_id is not None else user_id
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = resolved_chat_id
    if text is not None:
        update.message.text = text
    else:
        update.message.text = None
    update.message.reply_text = AsyncMock()
    update.callback_query = None
    return update


def make_cb_update(callback_data: str | None = None, user_id: int = 123456, chat_id: int | None = None) -> MagicMock:
    resolved_chat_id = chat_id if chat_id is not None else user_id
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = resolved_chat_id
    update.message = None

    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update.callback_query = query
    return update


# ============================================================================
# Scenario 1: Re-entry Robustness
# ============================================================================

@pytest.mark.asyncio
async def test_reentry_start_mid_phone_state(db: DatabaseConnection) -> None:
    """Sending /start while in PHONE state resets state and returns END."""
    user_repo = UserRepository(db)

    context = make_ctx(
        bot_data={"user_repo": user_repo, "pending_auth": {}},
        user_data={"current_state": PHONE},
    )
    update = make_msg_update(text="/start", user_id=1001)

    res = await start(update, context)
    assert res == ConversationHandler.END
    context.bot.send_message.assert_awaited_once()
    assert 1001 not in context.bot_data["pending_auth"]


@pytest.mark.asyncio
async def test_reentry_start_mid_code_disconnects_client() -> None:
    """Sending /start while awaiting SMS code disconnects pending client and clears pending_auth."""
    mock_client = MagicMock()
    mock_client.disconnect = AsyncMock()

    context = make_ctx(
        bot_data={
            "pending_auth": {
                2002: {
                    "phone": "+15156723850",
                    "client": mock_client,
                    "phone_code_hash": "hash_xyz",
                }
            }
        }
    )
    update = make_msg_update(text="/start", user_id=2002)

    res = await start(update, context)
    assert res == ConversationHandler.END
    mock_client.disconnect.assert_awaited_once()
    assert 2002 not in context.bot_data["pending_auth"]


@pytest.mark.asyncio
async def test_reentry_start_mid_2fa_disconnects_client() -> None:
    """Sending /start while awaiting 2FA password disconnects pending client and clears state."""
    mock_client = MagicMock()
    mock_client.disconnect = AsyncMock()

    context = make_ctx(
        bot_data={
            "pending_auth": {
                3003: {
                    "phone": "+15156723850",
                    "client": mock_client,
                }
            }
        },
        user_data={"awaiting_2fa": True},
    )
    update = make_msg_update(text="/start", user_id=3003)

    res = await start(update, context)
    assert res == ConversationHandler.END
    mock_client.disconnect.assert_awaited_once()
    assert 3003 not in context.bot_data["pending_auth"]


@pytest.mark.asyncio
async def test_reentry_cancel_mid_code_disconnects_client() -> None:
    """Sending /cancel while awaiting code cleanly releases client."""
    mock_client = MagicMock()
    mock_client.disconnect = AsyncMock()

    context = make_ctx(
        bot_data={
            "pending_auth": {
                4004: {
                    "phone": "+15156723850",
                    "client": mock_client,
                    "phone_code_hash": "hash_123",
                }
            }
        }
    )
    update = make_msg_update(text="/cancel", user_id=4004)

    res = await cancel(update, context)
    assert res == ConversationHandler.END
    mock_client.disconnect.assert_awaited_once()
    assert 4004 not in context.bot_data["pending_auth"]
    update.message.reply_text.assert_awaited_once()
    assert OPERATION_CANCELLED_TEXT in update.message.reply_text.call_args[1]["text"]


@pytest.mark.asyncio
async def test_reentry_cancel_mid_2fa_disconnects_client() -> None:
    """Sending /cancel while awaiting 2FA cleanly releases client and returns END."""
    mock_client = MagicMock()
    mock_client.disconnect = AsyncMock()

    context = make_ctx(
        bot_data={
            "pending_auth": {
                5005: {
                    "phone": "+15156723850",
                    "client": mock_client,
                }
            }
        }
    )
    update = make_msg_update(text="/cancel", user_id=5005)

    res = await cancel(update, context)
    assert res == ConversationHandler.END
    mock_client.disconnect.assert_awaited_once()
    assert 5005 not in context.bot_data["pending_auth"]


@pytest.mark.asyncio
async def test_reentry_cancel_auth_callback_disconnects_client() -> None:
    """Clicking cancel_auth inline button during auth disconnects client and edits message."""
    mock_client = MagicMock()
    mock_client.disconnect = AsyncMock()

    context = make_ctx(
        bot_data={
            "pending_auth": {
                6006: {
                    "phone": "+15156723850",
                    "client": mock_client,
                }
            }
        }
    )
    update = make_cb_update("cancel_auth", user_id=6006)

    res = await cancel_auth(update, context)
    assert res == ConversationHandler.END
    mock_client.disconnect.assert_awaited_once()
    assert 6006 not in context.bot_data["pending_auth"]
    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_rapid_consecutive_start_commands(db: DatabaseConnection) -> None:
    """10 rapid consecutive /start commands execute safely without hanging or errors."""
    user_repo = UserRepository(db)

    context = make_ctx(bot_data={"user_repo": user_repo, "pending_auth": {}})

    for i in range(10):
        update = make_msg_update(text="/start", user_id=7007)
        res = await start(update, context)
        assert res == ConversationHandler.END

    assert context.bot.send_message.await_count == 10
    user = await user_repo.get_user(7007)
    assert user is not None


@pytest.mark.asyncio
async def test_cancel_when_no_active_conversation() -> None:
    """Sending /cancel when idle does not raise error and returns END."""
    context = make_ctx(bot_data={"pending_auth": {}})
    update = make_msg_update(text="/cancel", user_id=8008)

    res = await cancel(update, context)
    assert res == ConversationHandler.END
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_with_db_failure_recovers_gracefully() -> None:
    """If database throws an exception during /start user creation, user still receives welcome."""
    mock_user_repo = MagicMock()
    mock_user_repo.get_or_create_user = AsyncMock(side_effect=RuntimeError("Disk I/O error"))

    context = make_ctx(bot_data={"user_repo": mock_user_repo, "pending_auth": {}})
    update = make_msg_update(text="/start", user_id=9009)

    res = await start(update, context)
    assert res == ConversationHandler.END
    context.bot.send_message.assert_awaited_once()
    sent_text = context.bot.send_message.call_args[1]["text"]
    assert "Telegram Account Manager Bot" in sent_text


@pytest.mark.asyncio
async def test_client_disconnect_exception_during_cleanup_handled() -> None:
    """If pending client disconnect() raises an exception, cleanup continues cleanly without raising."""
    faulty_client = MagicMock()
    faulty_client.disconnect = AsyncMock(side_effect=RuntimeError("Socket already dead"))

    context = make_ctx(
        bot_data={
            "pending_auth": {
                9999: {
                    "phone": "+15156723850",
                    "client": faulty_client,
                }
            }
        }
    )
    update = make_msg_update(text="/cancel", user_id=9999)

    res = await cancel(update, context)
    assert res == ConversationHandler.END
    assert 9999 not in context.bot_data["pending_auth"]


# ============================================================================
# Scenario 2: 2FA Challenge Flow
# ============================================================================

@pytest.mark.asyncio
async def test_2fa_full_challenge_flow_with_retry(db: DatabaseConnection) -> None:
    """Complete 2FA journey: valid code -> 2fa_required -> bad password retry -> good password success."""
    account_repo = AccountRepository(db)

    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_auth = MagicMock(spec=AuthService)

    # 1. Code requires 2FA
    mock_auth.sign_in = AsyncMock(
        return_value=SignInResult(status="2fa_required", phone="+15156723850")
    )
    # 2. First password attempt fails
    # 3. Second password attempt succeeds
    mock_auth.sign_in_2fa = AsyncMock(
        side_effect=[
            SignInResult(status="invalid_password", phone="+15156723850"),
            SignInResult(status="success", phone="+15156723850", user_id=555),
        ]
    )

    mock_client = MagicMock()
    context = make_ctx(
        bot_data={
            "session_manager": mock_sm,
            "auth_service": mock_auth,
            "account_repo": account_repo,
            "pending_auth": {
                1111: {
                    "phone": "+15156723850",
                    "client": mock_client,
                    "phone_code_hash": "hash_abc",
                }
            },
        }
    )

    # Step A: User submits code
    update_code = make_msg_update(text="12345", user_id=1111)
    res_code = await code_handler(update_code, context)
    assert res_code == WAITING_FOR_CODE
    assert context.user_data.get("awaiting_2fa") is True
    assert 1111 in context.bot_data["pending_auth"]
    update_code.message.reply_text.assert_awaited_once_with(TWO_FA_PROMPT)

    # Step B: User submits bad 2FA password (first retry)
    update_bad_pass = make_msg_update(text="wrong_pass", user_id=1111)
    res_bad = await password_handler(update_bad_pass, context)
    assert res_bad == WAITING_FOR_CODE
    assert 1111 in context.bot_data["pending_auth"]
    update_bad_pass.message.reply_text.assert_awaited_once_with(INVALID_PASSWORD_TEXT)

    # Step C: User submits correct 2FA password (second retry)
    update_good_pass = make_msg_update(text="correct_pass", user_id=1111)
    res_good = await password_handler(update_good_pass, context)
    assert res_good == ACCOUNT_ACTIONS
    assert 1111 not in context.bot_data["pending_auth"]
    assert context.user_data["current_phone"] == "+15156723850"

    # Verify account saved in DB
    account = await account_repo.get_account(1111, "+15156723850")
    assert account is not None


@pytest.mark.asyncio
async def test_2fa_flood_wait_disconnects_client() -> None:
    """When Telegram imposes flood wait on 2FA, client is disconnected and conversation terminates."""
    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_sm.disconnect = AsyncMock()

    mock_auth = MagicMock(spec=AuthService)
    mock_auth.sign_in_2fa = AsyncMock(
        return_value=SignInResult(status="flood_wait", phone="+15156723850", message="Wait 300s")
    )

    context = make_ctx(
        bot_data={
            "session_manager": mock_sm,
            "auth_service": mock_auth,
            "pending_auth": {
                2222: {
                    "phone": "+15156723850",
                    "client": MagicMock(),
                }
            },
        }
    )
    update = make_msg_update(text="some_pass", user_id=2222)

    res = await password_handler(update, context)
    assert res == ConversationHandler.END
    mock_sm.disconnect.assert_awaited_once_with("+15156723850")
    assert 2222 not in context.bot_data["pending_auth"]
    update.message.reply_text.assert_awaited_once()
    assert "Wait 300s" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_2fa_unhandled_telethon_exception_handled() -> None:
    """If sign_in_2fa raises an unhandled exception, handler disconnects client and ends cleanly."""
    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_sm.disconnect = AsyncMock()

    mock_auth = MagicMock(spec=AuthService)
    mock_auth.sign_in_2fa = AsyncMock(side_effect=RuntimeError("Connection terminated abruptly"))

    context = make_ctx(
        bot_data={
            "session_manager": mock_sm,
            "auth_service": mock_auth,
            "pending_auth": {
                3333: {
                    "phone": "+15156723850",
                    "client": MagicMock(),
                }
            },
        }
    )
    update = make_msg_update(text="password", user_id=3333)

    res = await password_handler(update, context)
    assert res == ConversationHandler.END
    mock_sm.disconnect.assert_awaited_once_with("+15156723850")
    assert 3333 not in context.bot_data["pending_auth"]
    update.message.reply_text.assert_awaited_once()
    assert "Connection terminated abruptly" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_2fa_non_text_message_ignored() -> None:
    """Non-text message (e.g. photo/document) while waiting for 2FA password keeps state without error."""
    context = make_ctx(bot_data={"pending_auth": {4444: {"phone": "+15156723850"}}})
    update = make_msg_update(text=None, user_id=4444)

    res = await password_handler(update, context)
    assert res == WAITING_FOR_CODE


# ============================================================================
# Scenario 3: Unauthorized or Expired Session Handling
# ============================================================================

@pytest.mark.asyncio
async def test_select_account_unauthorized_cleans_db_and_session(db: DatabaseConnection) -> None:
    """Selecting an account with an invalid/revoked Telethon session purges it and displays expired."""
    account_repo = AccountRepository(db)
    await account_repo.add_account(user_id=5000, phone="+15156723850", auto_create_user=True)

    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_sm.is_authorized = AsyncMock(return_value=False)
    mock_sm.remove_session_file = AsyncMock()

    context = make_ctx(
        bot_data={
            "session_manager": mock_sm,
            "account_repo": account_repo,
        }
    )
    update = make_cb_update("select_+15156723850", user_id=5000)

    res = await select_account_callback(update, context)
    assert res == ConversationHandler.END

    # Session file and DB record must be purged
    mock_sm.remove_session_file.assert_awaited_once_with("+15156723850")
    account = await account_repo.get_account(5000, "+15156723850")
    assert account is None

    update.callback_query.edit_message_text.assert_awaited_once()
    call_kwargs = update.callback_query.edit_message_text.call_args[1]
    assert SESSION_EXPIRED_TEXT in call_kwargs["text"]


@pytest.mark.asyncio
async def test_select_account_foreign_user_rejected(db: DatabaseConnection) -> None:
    """Attempting to select an account belonging to another user returns NOT FOUND."""
    account_repo = AccountRepository(db)
    # Account belongs to user 111, but user 222 attempts to select it
    await account_repo.add_account(user_id=111, phone="+15156723850", auto_create_user=True)

    mock_sm = MagicMock(spec=TelethonSessionManager)
    context = make_ctx(bot_data={"account_repo": account_repo, "session_manager": mock_sm})
    update = make_cb_update("select_+15156723850", user_id=222)

    res = await select_account_callback(update, context)
    assert res == ConversationHandler.END
    update.callback_query.edit_message_text.assert_awaited_once_with(text=ACCOUNT_NOT_FOUND_TEXT)


@pytest.mark.asyncio
async def test_code_handler_session_expired_without_pending() -> None:
    """Submitting code when pending_auth was cleared / timed out displays restart prompt."""
    context = make_ctx(bot_data={"pending_auth": {}})
    update = make_msg_update(text="12345", user_id=6000)

    res = await code_handler(update, context)
    assert res == ConversationHandler.END
    update.message.reply_text.assert_awaited_once_with(SESSION_EXPIRED_RESTART_TEXT)


@pytest.mark.asyncio
async def test_password_handler_session_expired_without_pending() -> None:
    """Submitting 2FA password when pending_auth is missing displays restart prompt."""
    context = make_ctx(bot_data={"pending_auth": {}})
    update = make_msg_update(text="secret_password", user_id=7000)

    res = await password_handler(update, context)
    assert res == ConversationHandler.END
    update.message.reply_text.assert_awaited_once_with(SESSION_EXPIRED_RESTART_TEXT)


@pytest.mark.asyncio
async def test_phone_handler_network_error_handled() -> None:
    """Network / MTProto error in send_code informs user and terminates conversation cleanly."""
    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_sm.is_authorized = AsyncMock(return_value=False)
    mock_auth = MagicMock(spec=AuthService)
    mock_auth.send_code = AsyncMock(side_effect=RuntimeError("Cannot reach Telegram servers"))

    context = make_ctx(
        bot_data={"session_manager": mock_sm, "auth_service": mock_auth, "pending_auth": {}}
    )
    update = make_msg_update(text="+15156723850", user_id=8000)

    res = await phone_handler(update, context)
    assert res == ConversationHandler.END
    update.message.reply_text.assert_awaited_once()
    assert "Cannot reach Telegram servers" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_contact_extraction_failure_retains_account_actions() -> None:
    """If Telethon fails during contact extraction, user is informed and actions menu is preserved."""
    mock_cs = MagicMock(spec=ContactService)
    mock_cs.extract_contacts_by_length = AsyncMock(side_effect=RuntimeError("Session revoked"))

    context = make_ctx(bot_data={"contact_service": mock_cs})
    update = make_cb_update("extract_7_+15156723850", user_id=9000)

    res = await extract_contacts_callback(update, context)
    assert res == ACCOUNT_ACTIONS
    assert context.bot.send_message.await_count == 2
    err_call = context.bot.send_message.call_args_list[0][1]["text"]
    assert "Error extracting contacts: Session revoked" in err_call


@pytest.mark.asyncio
async def test_list_creator_chats_failure_handled() -> None:
    """If Telethon fails during chat listing, error is displayed on screen and actions menu retained."""
    mock_chat_service = MagicMock(spec=ChatService)
    mock_chat_service.list_creator_chats = AsyncMock(side_effect=RuntimeError("AuthKeyUnregistered"))

    context = make_ctx(bot_data={"chat_service": mock_chat_service})
    update = make_cb_update("list_chats_+15156723850", user_id=9001)

    res = await list_chats_callback(update, context)
    assert res == ACCOUNT_ACTIONS
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "Error listing chats: AuthKeyUnregistered" in update.callback_query.edit_message_text.call_args[1]["text"]


@pytest.mark.asyncio
async def test_get_code_failure_handled() -> None:
    """If Telethon fails during login code retrieval, error is displayed on screen without crashing."""
    mock_chat_service = MagicMock(spec=ChatService)
    mock_chat_service.get_latest_login_message = AsyncMock(side_effect=RuntimeError("Timeout"))

    context = make_ctx(bot_data={"chat_service": mock_chat_service})
    update = make_cb_update("get_code_+15156723850", user_id=9002)

    res = await get_code_callback(update, context)
    assert res == ACCOUNT_ACTIONS
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "Timeout" in update.callback_query.edit_message_text.call_args[1]["text"]


# ============================================================================
# Scenario 4: Button Router Dispatch Edge Cases
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unknown_signal",
    [
        "unknown_action",
        "random_button_123",
        "foo_bar_baz",
        "",
        "   ",
        "---",
    ],
)
async def test_button_router_unknown_callbacks_answered_and_end(unknown_signal: str) -> None:
    """Unknown callback data is acknowledged via query.answer() and returns END without error."""
    context = make_ctx()
    update = make_cb_update(unknown_signal, user_id=10001)

    res = await button_router(update, context)
    assert res == ConversationHandler.END
    update.callback_query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_button_router_none_callback_data() -> None:
    """CallbackQuery with data=None is answered and safely returns END."""
    context = make_ctx()
    update = make_cb_update(None, user_id=10002)
    # Mock query.data as None
    update.callback_query.data = None

    res = await button_router(update, context)
    assert res == ConversationHandler.END
    update.callback_query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_button_router_no_callback_query() -> None:
    """Update without callback_query returns END immediately without exceptions."""
    context = make_ctx()
    update = make_msg_update(text="hello", user_id=10003)
    update.callback_query = None

    res = await button_router(update, context)
    assert res == ConversationHandler.END


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "truncated_callback",
    [
        "select_",
        "logout_",
        "check_contacts_",
        "extract_",
        "extract_7",
        "export_mutual_",
        "delete_contacts_",
        "confirm_delete_",
        "list_chats_",
        "get_code_",
    ],
)
async def test_button_router_malformed_truncated_prefixes(truncated_callback: str) -> None:
    """Malformed/truncated callback prefixes do not crash the bot and answer queries safely."""
    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_sm.is_authorized = AsyncMock(return_value=False)
    mock_sm.remove_session_file = AsyncMock()
    mock_auth = MagicMock(spec=AuthService)
    mock_auth.log_out = AsyncMock()
    mock_cs = MagicMock(spec=ContactService)
    mock_cs.get_contacts_summary = AsyncMock(return_value={})
    mock_cs.get_all_contacts = AsyncMock(return_value=[])
    mock_cs.get_mutual_contacts = AsyncMock(return_value=[])
    mock_chat_service = MagicMock(spec=ChatService)
    mock_chat_service.list_creator_chats = AsyncMock(return_value=[])
    mock_chat_service.get_latest_login_message = AsyncMock(return_value=None)

    context = make_ctx(
        bot_data={
            "pending_auth": {},
            "session_manager": mock_sm,
            "auth_service": mock_auth,
            "contact_service": mock_cs,
            "chat_service": mock_chat_service,
        }
    )
    update = make_cb_update(truncated_callback, user_id=10004)

    # Dispatch via button_router
    res = await button_router(update, context)
    # All handlers return an integer state (END or ACCOUNT_ACTIONS)
    assert isinstance(res, int)
    update.callback_query.answer.assert_awaited()


@pytest.mark.asyncio
async def test_concurrent_button_clicks_on_delete() -> None:
    """Simulate two concurrent button clicks on confirm_delete_ callback."""
    mock_cs = MagicMock(spec=ContactService)
    mock_cs.get_all_contacts = AsyncMock(return_value=[])  # Empty

    context = make_ctx(bot_data={"contact_service": mock_cs})
    update1 = make_cb_update("confirm_delete_+15156723850", user_id=10005)
    update2 = make_cb_update("confirm_delete_+15156723850", user_id=10005)

    res1, res2 = await asyncio.gather(
        confirm_delete_callback(update1, context),
        confirm_delete_callback(update2, context),
    )
    assert res1 == ACCOUNT_ACTIONS
    assert res2 == ACCOUNT_ACTIONS


@pytest.mark.asyncio
async def test_global_error_handler_with_and_without_chat() -> None:
    """Central error handler logs exceptions and sends error text if chat exists."""
    context = make_ctx()
    context.error = RuntimeError("Simulated crash")

    # 1. Update with chat
    update_with_chat = make_msg_update(text="crash", user_id=10006)
    await error_handler(update_with_chat, context)
    context.bot.send_message.assert_awaited_once_with(
        chat_id=10006,
        text=ERROR_SUPPORT_TEXT,
    )

    # 2. Update without chat (None)
    context.bot.send_message.reset_mock()
    await error_handler(None, context)
    context.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_fallback_message_handler() -> None:
    """Non-command text messages received outside active conversation receive fallback text."""
    context = make_ctx()
    update = make_msg_update(text="gibberish text", user_id=10007)

    await default_message_handler(update, context)
    update.message.reply_text.assert_awaited_once()
    assert DEFAULT_FALLBACK_TEXT in update.message.reply_text.call_args[1]["text"]


# ============================================================================
# ConversationHandler Full Flow Integration
# ============================================================================

def test_conversation_handler_configuration() -> None:
    """Verify ConversationHandler definition includes re-entry and proper state mappings."""
    conv = create_conversation_handler()
    assert conv.allow_reentry is True
    assert PHONE in conv.states
    assert CODE in conv.states
    assert WAITING_FOR_CODE in conv.states
    assert ACCOUNT_ACTIONS in conv.states
    assert len(conv.fallbacks) >= 2
