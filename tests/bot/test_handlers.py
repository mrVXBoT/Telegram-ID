"""
tests.bot.test_handlers
=======================
Automated unit and integration tests for bot handlers:
- Account selection & logout
- Contact inspection & digit length VCF extraction (in-memory streaming)
- Mutual contacts export
- Contact deletion flow (warning & live progress confirmation)
- Creator chats listing & 777000 login code retrieval
- Callback query button_router dispatching
- Global error handler & application factory
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from telegram.ext import ConversationHandler

from bot.application import build_application, create_conversation_handler
from bot.handlers import (
    button_router,
    check_contacts_callback,
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
    select_account_callback,
)
from bot.states import ACCOUNT_ACTIONS
from config.settings import Settings
from database.connection import DatabaseConnection
from database.repository import AccountRepository, OperationLogRepository, UserRepository
from services.auth_service import AuthService
from services.chat_service import ChatInfo, ChatService
from services.contact_service import ContactService, DeleteResult
from services.session_manager import TelethonSessionManager
from utils.vcf import ContactInfo


def make_context(bot_data: dict | None = None, user_data: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = bot_data if bot_data is not None else {}
    ctx.user_data = user_data if user_data is not None else {}
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_document = AsyncMock()
    return ctx


def make_callback_update(callback_data: str, user_id: int = 123456) -> MagicMock:
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = user_id
    update.message = None

    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update.callback_query = query
    return update


@pytest.mark.asyncio
async def test_list_accounts_empty_and_populated(db: DatabaseConnection) -> None:
    """Verify list_accounts shows empty prompt when no accounts, and list when accounts exist."""
    account_repo = AccountRepository(db)

    context = make_context(bot_data={"account_repo": account_repo})
    update = make_callback_update("list_accounts", user_id=123456)

    # 1. Empty accounts
    res = await list_accounts_callback(update, context)
    assert res == ConversationHandler.END
    call_args = update.callback_query.edit_message_text.call_args[1]
    assert "You don't have any accounts yet" in call_args["text"]

    # 2. Add an account and list again
    await account_repo.add_account(123456, "+15156723850", auto_create_user=True)
    update = make_callback_update("list_accounts", user_id=123456)
    res2 = await list_accounts_callback(update, context)
    assert res2 == ConversationHandler.END
    call_args2 = update.callback_query.edit_message_text.call_args[1]
    assert "📱 +15156723850" in call_args2["text"]


@pytest.mark.asyncio
async def test_select_account_valid_and_expired(db: DatabaseConnection) -> None:
    """Verify select_account handles valid sessions and expired sessions cleanly."""
    account_repo = AccountRepository(db)
    await account_repo.add_account(123456, "+15156723850", auto_create_user=True)

    mock_sm = MagicMock(spec=TelethonSessionManager)
    mock_sm.is_authorized = AsyncMock(return_value=True)
    context = make_context(bot_data={"account_repo": account_repo, "session_manager": mock_sm})

    # Authorized selection -> transitions to ACCOUNT_ACTIONS
    update = make_callback_update("select_+15156723850", user_id=123456)
    res = await select_account_callback(update, context)
    assert res == ACCOUNT_ACTIONS
    assert context.user_data["current_phone"] == "+15156723850"
    update.callback_query.edit_message_text.assert_awaited_once()

    # Expired session -> cleans session and DB, returns END
    mock_sm.is_authorized = AsyncMock(return_value=False)
    mock_sm.remove_session_file = AsyncMock(return_value=True)
    update_expired = make_callback_update("select_+15156723850", user_id=123456)
    res_expired = await select_account_callback(update_expired, context)
    assert res_expired == ConversationHandler.END
    mock_sm.remove_session_file.assert_awaited_once_with("+15156723850")
    assert await account_repo.get_account(123456, "+15156723850") is None


@pytest.mark.asyncio
async def test_logout_account_cleans_session_and_db(db: DatabaseConnection) -> None:
    """Verify logout terminates session, removes DB record, and logs operation."""
    account_repo = AccountRepository(db)
    op_repo = OperationLogRepository(db)
    await account_repo.add_account(123456, "+15156723850", auto_create_user=True)

    mock_auth = MagicMock(spec=AuthService)
    mock_auth.log_out = AsyncMock(return_value=True)

    context = make_context(
        bot_data={
            "account_repo": account_repo,
            "op_repo": op_repo,
            "auth_service": mock_auth,
        }
    )
    update = make_callback_update("logout_+15156723850", user_id=123456)

    res = await logout_account_callback(update, context)
    assert res == ConversationHandler.END

    mock_auth.log_out.assert_awaited_once_with("+15156723850")
    assert await account_repo.get_account(123456, "+15156723850") is None

    logs = await op_repo.get_user_history(123456)
    assert len(logs) == 1
    assert logs[0].action == "logout"
    assert logs[0].phone_number == "+15156723850"

    update.callback_query.edit_message_text.assert_awaited_once()
    assert "Successfully logged out" in update.callback_query.edit_message_text.call_args[1]["text"]


@pytest.mark.asyncio
async def test_check_contacts_summary() -> None:
    """Verify check_contacts queries service and edits message with overview."""
    mock_cs = MagicMock(spec=ContactService)
    mock_cs.get_contacts_summary = AsyncMock(
        return_value={
            "total": 50,
            "mutual": 20,
            "breakdown": {7: 10, 8: 15, 9: 25, 10: 0, 11: 0},
            "samples": [ContactInfo(id=1234567, first_name="John")],
        }
    )

    context = make_context(bot_data={"contact_service": mock_cs})
    update = make_callback_update("check_contacts_+15156723850")

    res = await check_contacts_callback(update, context)
    assert res == ACCOUNT_ACTIONS
    mock_cs.get_contacts_summary.assert_awaited_once_with("+15156723850")

    # Second edit call has the summary text
    last_edit = update.callback_query.edit_message_text.call_args[1]["text"]
    assert "Total contacts: 50" in last_edit
    assert "Mutual contacts: 20" in last_edit


@pytest.mark.asyncio
async def test_extract_contacts_streaming_vcf() -> None:
    """
    Verify extract_contacts streams VCF document directly in memory without disk I/O,
    attaching the exact expected filename and caption.
    """
    mock_cs = MagicMock(spec=ContactService)
    mock_contacts = [
        ContactInfo(id=1234567, phone="+15551234567", first_name="Test", last_name="User"),
        ContactInfo(id=7654321, phone=None),
    ]
    mock_cs.extract_contacts_by_length = AsyncMock(return_value=mock_contacts)

    context = make_context(bot_data={"contact_service": mock_cs})
    update = make_callback_update("extract_7_+15156723850", user_id=123456)

    res = await extract_contacts_callback(update, context)
    assert res == ACCOUNT_ACTIONS

    mock_cs.extract_contacts_by_length.assert_awaited_once_with("+15156723850", "7")

    # Verify intermediate progress message sent
    assert context.bot.send_message.await_count >= 2

    # Verify document delivery
    context.bot.send_document.assert_awaited_once()
    doc_args = context.bot.send_document.call_args[1]
    assert doc_args["filename"] == "+15156723850_7digit_contacts.vcf"
    assert "Found 2 contacts with 7 digit IDs" in doc_args["caption"]

    # Verify document stream is io.BytesIO with valid vCard content
    stream = doc_args["document"]
    assert isinstance(stream, io.BytesIO)
    content = stream.getvalue().decode("utf-8")
    assert "BEGIN:VCARD" in content
    assert "FN:1234567" in content
    assert "FN:7654321" in content


@pytest.mark.asyncio
async def test_extract_contacts_none_found() -> None:
    """Verify extracting contacts when none found informs user without error."""
    mock_cs = MagicMock(spec=ContactService)
    mock_cs.extract_contacts_by_length = AsyncMock(return_value=[])

    context = make_context(bot_data={"contact_service": mock_cs})
    update = make_callback_update("extract_7to9_+15156723850", user_id=123456)

    res = await extract_contacts_callback(update, context)
    assert res == ACCOUNT_ACTIONS

    context.bot.send_document.assert_not_called()
    # Should send "No contacts with 7to9 digit IDs found."
    sent_texts = [call[1]["text"] for call in context.bot.send_message.call_args_list]
    assert any("No contacts with 7to9 digit IDs found" in t for t in sent_texts)


@pytest.mark.asyncio
async def test_export_mutual_contacts_streaming_vcf() -> None:
    """Verify mutual contacts export generates VCF and delivers via send_document."""
    mock_cs = MagicMock(spec=ContactService)
    mutuals = [ContactInfo(id=9876543, phone="+19998887766", is_mutual=True)]
    mock_cs.get_mutual_contacts = AsyncMock(return_value=mutuals)

    context = make_context(bot_data={"contact_service": mock_cs})
    update = make_callback_update("export_mutual_+15156723850", user_id=123456)

    res = await export_mutual_callback(update, context)
    assert res == ACCOUNT_ACTIONS

    context.bot.send_document.assert_awaited_once()
    doc_args = context.bot.send_document.call_args[1]
    assert doc_args["filename"] == "+15156723850_mutual_contacts.vcf"
    assert "Exported 1 mutual contacts" in doc_args["caption"]


@pytest.mark.asyncio
async def test_delete_contacts_warning_and_confirmation() -> None:
    """Verify delete warning presents bilingual confirmation, and confirm executes deletion."""
    mock_cs = MagicMock(spec=ContactService)
    contacts = [ContactInfo(id=1), ContactInfo(id=2)]
    mock_cs.get_all_contacts = AsyncMock(return_value=contacts)
    mock_cs.delete_all_contacts = AsyncMock(
        return_value=DeleteResult(total=2, deleted=2, failed=0, status="success")
    )

    context = make_context(bot_data={"contact_service": mock_cs})

    # Step 1: Warning
    update_warn = make_callback_update("delete_contacts_+15156723850")
    res_warn = await delete_contacts_callback(update_warn, context)
    assert res_warn == ACCOUNT_ACTIONS
    warn_text = update_warn.callback_query.edit_message_text.call_args[1]["text"]
    assert "⚠️ Warning!" in warn_text
    assert "2" in warn_text

    # Step 2: Confirmation
    update_conf = make_callback_update("confirm_delete_+15156723850")
    res_conf = await confirm_delete_callback(update_conf, context)
    assert res_conf == ACCOUNT_ACTIONS
    mock_cs.delete_all_contacts.assert_awaited_once()

    final_text = update_conf.callback_query.edit_message_text.call_args[1]["text"]
    assert "Contact deletion completed" in final_text
    assert "Deleted: 2" in final_text


@pytest.mark.asyncio
async def test_list_chats_displays_formatted_inventory() -> None:
    """Verify list_chats queries service and displays formatted inventory."""
    mock_chats = [
        ChatInfo(
            id=101,
            title="Channel 1",
            type="channel",
            link="https://t.me/ch1",
            creation_date="2022-05-01",
            creation_year=2022,
            history_visibility="Visible",
        )
    ]
    mock_chat_service = MagicMock(spec=ChatService)
    mock_chat_service.list_creator_chats = AsyncMock(return_value=mock_chats)

    context = make_context(bot_data={"chat_service": mock_chat_service})
    update = make_callback_update("list_chats_+15156723850")

    res = await list_chats_callback(update, context)
    assert res == ACCOUNT_ACTIONS
    mock_chat_service.list_creator_chats.assert_awaited_once_with("+15156723850")

    text = update.callback_query.edit_message_text.call_args[1]["text"]
    assert "کانال‌های شما / Your Channels" in text
    assert "Channel 1" in text


@pytest.mark.asyncio
async def test_get_code_retrieves_latest_code() -> None:
    """Verify get_code extracts official code message from peer 777000."""
    mock_chat_service = MagicMock(spec=ChatService)
    mock_chat_service.get_latest_login_message = AsyncMock(
        return_value="Telegram code: 82914. Do not share."
    )

    context = make_context(bot_data={"chat_service": mock_chat_service})
    update = make_callback_update("get_code_+15156723850")

    res = await get_code_callback(update, context)
    assert res == ACCOUNT_ACTIONS

    text = update.callback_query.edit_message_text.call_args[1]["text"]
    assert "82914" in text


@pytest.mark.asyncio
async def test_button_router_dispatch() -> None:
    """Verify button_router accurately dispatches various callback query signals."""
    context = make_context()

    # Route cancel_auth
    u1 = make_callback_update("cancel_auth")
    assert await button_router(u1, context) == ConversationHandler.END

    # Route back_to_menu
    u2 = make_callback_update("back_to_menu")
    assert await button_router(u2, context) == ConversationHandler.END

    # Route add_account
    u3 = make_callback_update("add_account")
    assert await button_router(u3, context) == 0  # PHONE state


@pytest.mark.asyncio
async def test_default_message_handler() -> None:
    """Verify default_message_handler replies with instructions."""
    context = make_context()
    update = MagicMock()
    update.message.reply_text = AsyncMock()

    await default_message_handler(update, context)
    update.message.reply_text.assert_awaited_once()
    assert "Please send /start" in update.message.reply_text.call_args[1]["text"]


@pytest.mark.asyncio
async def test_error_handler_logs_and_notifies() -> None:
    """Verify error_handler notifies user chat without crashing."""
    context = make_context()
    context.error = ValueError("Something broke")
    update = MagicMock()
    update.effective_chat.id = 123456

    await error_handler(update, context)
    context.bot.send_message.assert_awaited_once()
    assert "contact support" in context.bot.send_message.call_args[1]["text"]


def test_build_application_factory() -> None:
    """Verify build_application sets up Application with hooks, bot_data, and conversation handler."""
    settings = Settings(
        api_id=12345,
        api_hash="mock_hash",
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        database_path=":memory:",
    )
    db = DatabaseConnection(":memory:")
    sm = TelethonSessionManager(settings=settings)

    app = build_application(settings=settings, db_conn=db, session_manager=sm)
    assert app is not None
    assert app.bot_data["settings"] == settings
    assert app.bot_data["db"] == db
    assert app.bot_data["session_manager"] == sm
    assert "auth_service" in app.bot_data
    assert "contact_service" in app.bot_data
    assert "chat_service" in app.bot_data

    # Verify conversation handler is registered
    conv_handler = create_conversation_handler()
    assert isinstance(conv_handler, ConversationHandler)
    assert conv_handler.allow_reentry is True
