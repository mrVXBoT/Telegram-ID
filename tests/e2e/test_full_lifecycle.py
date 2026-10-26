"""
tests.e2e.test_full_lifecycle
=============================
Opaque-box End-to-End (E2E) integration test suite validating the entire
6-layer architecture across all core application lifecycle workflows:

- Scenario 1: JSON Migration -> Startup Lifecycle -> Multi-Account Selection -> VCF Export
  Legacy user_data.json on disk -> build_application post_init auto_migrate -> .bak creation
  -> /start account listing -> select_account -> extract_7 streaming RFC-3.0 vCard in-memory.
- Scenario 2: New Account Auth -> 2FA Challenge -> Batch Contact Deletion -> Safe Logout
  /start -> add_account -> phone_handler -> code_handler -> 2FA SessionPasswordNeededError
  -> password_handler -> check_contacts -> batch delete with live progress -> logout & DB unbind.
- Scenario 3: Creator Dialogs Inventory & Peer 777000 Code Extraction
  list_chats -> supergroup deduplication (migrated basic chats omitted) -> hidden_prehistory probe
  -> get_code -> peer 777000 official 5-digit verification code extraction (r'\\b(\\d{5})\\b').
- Scenario 4: Application Termination & Windows Resource Hygiene
  build_application lifecycle bootstrap -> session connection pool registration -> post_shutdown
  cleanup -> complete socket/db handle release -> zero WinError 32 file locks on Windows.
- Scenario 5: Universal Re-Entry & State Reset Across All Conversation States
  Verifies re-entry with /start and /cancel during PHONE, CODE, WAITING_FOR_CODE, and ACCOUNT_ACTIONS.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import ConversationHandler
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.contacts import DeleteContactsRequest, GetContactsRequest
from telethon.tl.functions.messages import ExportChatInviteRequest, GetDialogsRequest
from telethon.tl.types import Channel, Chat

from bot.application import build_application
from bot.handlers import (
    add_account_callback,
    button_router,
    cancel,
    check_contacts_callback,
    code_handler,
    confirm_delete_callback,
    delete_contacts_callback,
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
    INVALID_PASSWORD_TEXT,
    NO_CODE_FOUND_TEXT,
)
from bot.states import ACCOUNT_ACTIONS, CODE, PHONE, WAITING_FOR_CODE
from config.settings import Settings
from database.connection import DatabaseConnection
from database.repository import AccountRepository, OperationLogRepository, UserRepository
from services.auth_service import AuthService, SignInResult
from services.chat_service import ChatService
from services.contact_service import ContactService, DeleteResult
from services.session_manager import TelethonSessionManager
from utils.vcf import ContactInfo


# ============================================================================
# Test Fixture Helpers
# ============================================================================

def make_e2e_context(
    bot_data: dict | None = None,
    user_data: dict | None = None,
) -> MagicMock:
    """Create a mock ContextTypes.DEFAULT_TYPE populated with app services."""
    ctx = MagicMock()
    ctx.bot_data = bot_data if bot_data is not None else {}
    ctx.user_data = user_data if user_data is not None else {}
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_document = AsyncMock()
    return ctx


def make_e2e_message_update(
    text: str,
    user_id: int = 10001,
    chat_id: int | None = None,
) -> MagicMock:
    """Create a mock Telegram message Update."""
    resolved_chat = chat_id if chat_id is not None else user_id
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = resolved_chat
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.callback_query = None
    return update


def make_e2e_callback_update(
    callback_data: str,
    user_id: int = 10001,
    chat_id: int | None = None,
) -> MagicMock:
    """Create a mock Telegram callback_query Update."""
    resolved_chat = chat_id if chat_id is not None else user_id
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = resolved_chat
    update.message = None

    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update.callback_query = query
    return update


# ============================================================================
# Scenario 1: JSON Migration -> Startup Lifecycle -> Account Selection -> VCF Export
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_1_migration_startup_and_vcf_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Tier 4 E2E Scenario 1:
    1. Legacy user_data.json exists on disk with multiple accounts.
    2. build_application runs auto_migrate in post_init hook.
    3. Backup file user_data.json.bak is created and verified.
    4. User issues /start -> accounts are listed.
    5. User selects account via select_{phone}.
    6. User triggers extract_7_{phone} -> send_document receives in-memory io.BytesIO
       containing valid RFC-compliant vCard 3.0 records (BEGIN:VCARD ... END:VCARD).
    """
    # 1. Prepare legacy user_data.json on disk
    user_id = 8881001
    primary_phone = "+15156723850"
    secondary_phone = "+15559876543"

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Primary account has active .session file on disk
    session_file_primary = sessions_dir / f"{primary_phone}.session"
    session_file_primary.write_bytes(b"TELETHON_MOCK_SESSION_BYTES_888")

    # Secondary account intentionally lacks a .session file to test missing_session handling
    legacy_data = {
        str(user_id): {
            "accounts": {
                primary_phone: {"added_at": "2026-01-15T12:00:00Z"},
                secondary_phone: {"added_at": "2026-02-10T14:30:00Z"},
            }
        }
    }
    json_path = tmp_path / "user_data.json"
    json_path.write_text(json.dumps(legacy_data), encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    # 2. Configure Settings and build Application
    db_path = tmp_path / "bot_e2e_s1.db"
    settings = Settings(
        api_id=12345,
        api_hash="mock_api_hash_s1",
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        database_path=db_path,
        sessions_dir=sessions_dir,
    )

    app = build_application(settings=settings)
    assert app is not None

    # 3. Execute post_init lifecycle hook (auto_migrate + DB init)
    await app.post_init(app)

    # Verify backup file creation
    bak_path = tmp_path / "user_data.json.bak"
    assert bak_path.is_file(), "Backup file user_data.json.bak was not created by auto_migrate."
    assert json.loads(bak_path.read_text(encoding="utf-8")) == legacy_data

    # Verify SQLite persistence
    account_repo: AccountRepository = app.bot_data["account_repo"]
    migrated_accounts = await account_repo.get_user_accounts(user_id)
    assert len(migrated_accounts) == 2

    acc_map = {acc.phone_number: acc for acc in migrated_accounts}
    assert primary_phone in acc_map
    assert acc_map[primary_phone].status == "active"
    assert secondary_phone in acc_map
    assert acc_map[secondary_phone].status == "missing_session"

    # 4. User issues /start
    context = make_e2e_context(bot_data=app.bot_data)
    update_start = make_e2e_message_update("/start", user_id=user_id)
    start_res = await start(update_start, context)
    assert start_res == ConversationHandler.END

    context.bot.send_message.assert_awaited()
    welcome_text = context.bot.send_message.call_args[1]["text"]
    assert "Telegram Account Manager" in welcome_text

    # 5. User views account list via callback
    update_list = make_e2e_callback_update("list_accounts", user_id=user_id)
    list_res = await list_accounts_callback(update_list, context)
    assert list_res == ConversationHandler.END

    list_text = update_list.callback_query.edit_message_text.call_args[1]["text"]
    assert primary_phone in list_text
    assert secondary_phone in list_text

    # 6. User selects primary account
    # Configure mock Telethon client with authorized session
    mock_client = AsyncMock()
    mock_client.is_connected = MagicMock(return_value=True)
    mock_client.is_user_authorized = AsyncMock(return_value=True)

    session_manager: TelethonSessionManager = app.bot_data["session_manager"]
    session_manager._clients[primary_phone] = mock_client
    session_manager.is_authorized = AsyncMock(return_value=True)

    update_select = make_e2e_callback_update(f"select_{primary_phone}", user_id=user_id)
    select_res = await select_account_callback(update_select, context)
    assert select_res == ACCOUNT_ACTIONS
    assert context.user_data["current_phone"] == primary_phone

    select_text = update_select.callback_query.edit_message_text.call_args[1]["text"]
    assert primary_phone in select_text
    assert "What would you like to do" in select_text

    # 7. User triggers extract_7_{phone} (7-digit ID contacts extraction)
    # Configure Telethon GetContactsRequest with raw users
    user_7digit_1 = MagicMock()
    user_7digit_1.id = 1234567  # 7 digits
    user_7digit_1.phone = "+15551234567"
    user_7digit_1.first_name = "Alice"
    user_7digit_1.last_name = "Smith"
    user_7digit_1.mutual_contact = True

    user_7digit_2 = MagicMock()
    user_7digit_2.id = 7654321  # 7 digits
    user_7digit_2.phone = "+15557654321"
    user_7digit_2.first_name = "Bob"
    user_7digit_2.last_name = None
    user_7digit_2.mutual_contact = False

    user_8digit = MagicMock()
    user_8digit.id = 87654321  # 8 digits (must be filtered out)
    user_8digit.phone = "+15558889900"
    user_8digit.first_name = "Charlie"
    user_8digit.last_name = "Brown"

    user_6digit = MagicMock()
    user_6digit.id = 999888  # 6 digits (must be filtered out)
    user_6digit.phone = "+15550001122"
    user_6digit.first_name = "ShortID"
    user_6digit.last_name = None

    mock_contacts_response = MagicMock()
    mock_contacts_response.contacts = [
        MagicMock(user_id=1234567, mutual=True),
        MagicMock(user_id=7654321, mutual=False),
        MagicMock(user_id=87654321, mutual=False),
    ]
    mock_contacts_response.users = [user_7digit_1, user_7digit_2, user_8digit, user_6digit]

    mock_client.side_effect = lambda req: (
        mock_contacts_response if isinstance(req, GetContactsRequest) else None
    )

    update_extract = make_e2e_callback_update(f"extract_7_{primary_phone}", user_id=user_id)
    extract_res = await extract_contacts_callback(update_extract, context)
    assert extract_res == ACCOUNT_ACTIONS

    # Verify send_document received in-memory io.BytesIO stream
    context.bot.send_document.assert_awaited_once()
    doc_call_args = context.bot.send_document.call_args[1]
    assert doc_call_args["chat_id"] == user_id
    assert doc_call_args["filename"] == f"{primary_phone}_7digit_contacts.vcf"
    assert "Found 2 contacts with 7 digit IDs" in doc_call_args["caption"]

    vcf_stream = doc_call_args["document"]
    assert isinstance(vcf_stream, io.BytesIO), "Document delivered was not an in-memory BytesIO stream."

    vcf_content = vcf_stream.getvalue().decode("utf-8")
    assert "BEGIN:VCARD" in vcf_content
    assert "VERSION:3.0" in vcf_content
    assert "Alice" in vcf_content or "1234567" in vcf_content
    assert "Bob" in vcf_content or "7654321" in vcf_content
    assert "END:VCARD" in vcf_content

    # Strict filtering: 8-digit and 6-digit users must not appear in the 7-digit export
    assert "Charlie" not in vcf_content
    assert "87654321" not in vcf_content
    assert "ShortID" not in vcf_content
    assert "999888" not in vcf_content

    # Safe post_shutdown cleanup
    await app.post_shutdown(app)


# ============================================================================
# Scenario 2: New Account Auth -> 2FA Challenge -> Batch Delete -> Logout
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_2_auth_2fa_batch_delete_and_logout(tmp_path: Path) -> None:
    """
    Tier 4 E2E Scenario 2:
    1. New user issues /start -> user record created.
    2. User clicks add_account -> transitions to PHONE state.
    3. User submits phone -> requests SMS code -> transitions to CODE state.
    4. User enters SMS code -> Telethon raises SessionPasswordNeededError
       -> transitions to WAITING_FOR_CODE state.
    5. User attempts invalid 2FA password -> stays in WAITING_FOR_CODE with warning.
    6. User submits valid 2FA password -> signs in -> transitions to ACCOUNT_ACTIONS
       -> account persisted to SQLite.
    7. User checks contact summary -> verifies total, mutual, breakdown.
    8. User confirms batch contact deletion -> live UI progress edits -> deletion verified.
    9. User clicks logout_{phone} -> session disconnected, DB record removed, operation logged.
    """
    db_path = tmp_path / "bot_e2e_s2.db"
    sessions_dir = tmp_path / "sessions_s2"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        api_id=54321,
        api_hash="mock_api_hash_s2",
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        database_path=db_path,
        sessions_dir=sessions_dir,
    )

    app = build_application(settings=settings)
    await app.post_init(app)

    user_id = 9992002
    phone_target = "+15156723850"
    user_repo: UserRepository = app.bot_data["user_repo"]
    account_repo: AccountRepository = app.bot_data["account_repo"]
    op_repo: OperationLogRepository = app.bot_data["op_repo"]
    auth_service: AuthService = app.bot_data["auth_service"]
    contact_service: ContactService = app.bot_data["contact_service"]
    session_manager: TelethonSessionManager = app.bot_data["session_manager"]

    context = make_e2e_context(bot_data=app.bot_data)

    # 1. New user issues /start
    update_start = make_e2e_message_update("/start", user_id=user_id)
    res_start = await start(update_start, context)
    assert res_start == ConversationHandler.END

    db_user = await user_repo.get_user(user_id)
    assert db_user is not None
    assert db_user.user_id == user_id

    # 2. Clicks add_account
    update_add = make_e2e_callback_update("add_account", user_id=user_id)
    res_add = await add_account_callback(update_add, context)
    assert res_add == PHONE
    add_prompt = update_add.callback_query.edit_message_text.call_args[1]["text"]
    assert "Please send your phone number" in add_prompt

    # 3. Submits phone number
    mock_client = AsyncMock()
    mock_client.is_connected = MagicMock(return_value=True)
    session_manager.get_client = AsyncMock(return_value=mock_client)
    session_manager.is_authorized = AsyncMock(return_value=False)
    auth_service.send_code = AsyncMock(return_value="mock_phone_hash_98765")

    update_phone = make_e2e_message_update(phone_target, user_id=user_id)
    res_phone = await phone_handler(update_phone, context)
    assert res_phone == CODE
    assert user_id in context.bot_data["pending_auth"]
    assert context.bot_data["pending_auth"][user_id]["phone"] == phone_target
    assert context.bot_data["pending_auth"][user_id]["phone_code_hash"] == "mock_phone_hash_98765"

    phone_ack = update_phone.message.reply_text.call_args[1]["text"]
    assert f"Verification code sent to {phone_target}" in phone_ack

    # 4. Enters SMS code -> Triggers 2FA SessionPasswordNeededError
    auth_service.sign_in = AsyncMock(
        return_value=SignInResult(status="2fa_required", phone=phone_target)
    )

    update_code = make_e2e_message_update("48291", user_id=user_id)
    res_code = await code_handler(update_code, context)
    assert res_code == WAITING_FOR_CODE
    assert context.user_data.get("awaiting_2fa") is True

    two_fa_prompt = update_code.message.reply_text.call_args[0][0]
    assert "two-factor authentication" in two_fa_prompt.lower()

    # 5. Adversarial: Submits incorrect 2FA password first
    auth_service.sign_in_2fa = AsyncMock(
        return_value=SignInResult(status="invalid_password", phone=phone_target)
    )

    update_wrong_pass = make_e2e_message_update("wrong_pass_attempt", user_id=user_id)
    res_wrong_pass = await password_handler(update_wrong_pass, context)
    assert res_wrong_pass == WAITING_FOR_CODE
    wrong_pass_msg = update_wrong_pass.message.reply_text.call_args[0][0]
    assert INVALID_PASSWORD_TEXT in wrong_pass_msg

    # 6. Submits correct 2FA password
    auth_service.sign_in_2fa = AsyncMock(
        return_value=SignInResult(status="success", phone=phone_target, user_id=user_id)
    )

    update_correct_pass = make_e2e_message_update("correct_master_pw_99", user_id=user_id)
    res_pass = await password_handler(update_correct_pass, context)
    assert res_pass == ACCOUNT_ACTIONS
    assert user_id not in context.bot_data["pending_auth"]
    assert context.user_data["current_phone"] == phone_target

    login_success_text = update_correct_pass.message.reply_text.call_args[1]["text"]
    assert "Successfully logged in" in login_success_text

    # Account must now be persisted in SQLite database
    saved_account = await account_repo.get_account(user_id, phone_target)
    assert saved_account is not None
    assert saved_account.phone_number == phone_target
    assert saved_account.status == "active"

    # 7. User checks contact summary
    contact_service.get_contacts_summary = AsyncMock(
        return_value={
            "total": 120,
            "mutual": 45,
            "breakdown": {7: 40, 8: 50, 9: 30, 10: 0, 11: 0},
            "samples": [ContactInfo(id=1111111, first_name="SampleContact")],
        }
    )

    update_summary = make_e2e_callback_update(f"check_contacts_{phone_target}", user_id=user_id)
    res_summary = await check_contacts_callback(update_summary, context)
    assert res_summary == ACCOUNT_ACTIONS

    summary_text = update_summary.callback_query.edit_message_text.call_args[1]["text"]
    assert "Total contacts: 120" in summary_text
    assert "Mutual contacts: 45" in summary_text

    # 8. User requests contact deletion warning
    dummy_contacts = [ContactInfo(id=i, first_name=f"User{i}") for i in range(120)]
    contact_service.get_all_contacts = AsyncMock(return_value=dummy_contacts)

    update_del_warn = make_e2e_callback_update(f"delete_contacts_{phone_target}", user_id=user_id)
    res_del_warn = await delete_contacts_callback(update_del_warn, context)
    assert res_del_warn == ACCOUNT_ACTIONS

    warn_text = update_del_warn.callback_query.edit_message_text.call_args[1]["text"]
    assert "Warning" in warn_text
    assert "120" in warn_text

    # User confirms batch deletion with simulated progress callback
    async def simulated_delete_all(phone: str, progress_callback=None, batch_delay=1.0):
        if progress_callback:
            # Simulate progress intervals: 100/120 then 120/120
            await progress_callback(100, 120)
            await progress_callback(120, 120)
        return DeleteResult(total=120, deleted=120, failed=0, status="success")

    contact_service.delete_all_contacts = AsyncMock(side_effect=simulated_delete_all)

    update_del_confirm = make_e2e_callback_update(f"confirm_delete_{phone_target}", user_id=user_id)
    res_del_confirm = await confirm_delete_callback(update_del_confirm, context)
    assert res_del_confirm == ACCOUNT_ACTIONS

    # Verify query.edit_message_text was called multiple times for live UI progress
    assert update_del_confirm.callback_query.edit_message_text.await_count >= 3
    final_del_text = update_del_confirm.callback_query.edit_message_text.call_args[1]["text"]
    assert "Contact deletion completed" in final_del_text
    assert "Deleted: 120" in final_del_text

    # 9. User clicks logout_{phone}
    auth_service.log_out = AsyncMock(return_value=True)

    update_logout = make_e2e_callback_update(f"logout_{phone_target}", user_id=user_id)
    res_logout = await logout_account_callback(update_logout, context)
    assert res_logout == ConversationHandler.END

    auth_service.log_out.assert_awaited_once_with(phone_target)

    # Verify account is unbound from SQLite
    assert await account_repo.get_account(user_id, phone_target) is None

    # Verify operation audit log
    logs = await op_repo.get_user_history(user_id)
    assert any(log.action == "logout" and log.phone_number == phone_target for log in logs)

    logout_text = update_logout.callback_query.edit_message_text.call_args[1]["text"]
    assert "Successfully logged out" in logout_text

    # Clean shutdown
    await app.post_shutdown(app)


# ============================================================================
# Scenario 3: Creator Chats Inventory & 777000 Code Retrieval
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_3_creator_chats_and_777000_code_retrieval(tmp_path: Path) -> None:
    """
    Tier 4 E2E Scenario 3:
    1. Account is linked with user.
    2. User triggers list_chats_{phone}:
       - Queries user-created channels, supergroups, basic chats.
       - Verifies deduplication: basic chat that was migrated to supergroup is omitted.
       - Verifies hidden_prehistory probe on supergroups and channels.
       - Verifies non-creator chats are excluded.
    3. User triggers get_code_{phone}:
       - Queries official peer 777000.
       - Verifies regex extraction of 5-digit verification code (r'\\b(\\d{5})\\b').
       - Displays formatted code banner.
       - Gracefully handles absent codes.
    """
    db_path = tmp_path / "bot_e2e_s3.db"
    sessions_dir = tmp_path / "sessions_s3"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        api_id=98765,
        api_hash="mock_api_hash_s3",
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        database_path=db_path,
        sessions_dir=sessions_dir,
    )

    app = build_application(settings=settings)
    await app.post_init(app)

    user_id = 7773003
    phone_target = "+15156723850"

    account_repo: AccountRepository = app.bot_data["account_repo"]
    await account_repo.add_account(user_id, phone_target, auto_create_user=True)

    session_manager: TelethonSessionManager = app.bot_data["session_manager"]
    mock_client = AsyncMock()
    mock_client.is_connected = MagicMock(return_value=True)
    mock_client.is_user_authorized = AsyncMock(return_value=True)

    # Configure Dialogs & Chats:
    # 1. Broadcast channel owned by user
    chan1 = MagicMock(spec=Channel)
    chan1.id = 10101
    chan1.title = "Official Crypto News"
    chan1.creator = True
    chan1.megagroup = False
    chan1.username = "cryptonews_hq"

    # 2. Supergroup owned by user, with hidden_prehistory=True, migrated from basic group 30303
    supergroup1 = MagicMock(spec=Channel)
    supergroup1.id = 20202
    supergroup1.title = "Crypto Community Supergroup"
    supergroup1.creator = True
    supergroup1.megagroup = True
    supergroup1.username = None

    # 3. Legacy Basic Chat that was migrated into supergroup1
    basic_chat_migrated = MagicMock(spec=Chat)
    basic_chat_migrated.id = 30303
    basic_chat_migrated.title = "Old Basic Team Chat"
    basic_chat_migrated.creator = True

    # 4. Supergroup owned by user with visible prehistory (hidden_prehistory=False)
    supergroup2 = MagicMock(spec=Channel)
    supergroup2.id = 40404
    supergroup2.title = "Public Builders Supergroup"
    supergroup2.creator = True
    supergroup2.megagroup = True
    supergroup2.username = "builders_sg"

    # 5. Chat NOT created by user (creator=False)
    chan_not_mine = MagicMock(spec=Channel)
    chan_not_mine.id = 99999
    chan_not_mine.title = "Someone Else Channel"
    chan_not_mine.creator = False
    chan_not_mine.megagroup = False

    dialogs_mock = MagicMock()
    dialogs_mock.chats = [
        chan1,
        supergroup1,
        basic_chat_migrated,
        supergroup2,
        chan_not_mine,
    ]

    # Full channel info mocks
    full_sg1 = MagicMock()
    full_sg1.full_chat.migrated_from_chat_id = 30303  # Indicates migration from 30303
    full_sg1.full_chat.hidden_prehistory = True

    full_sg2 = MagicMock()
    full_sg2.full_chat.migrated_from_chat_id = None
    full_sg2.full_chat.hidden_prehistory = False

    full_chan1 = MagicMock()
    full_chan1.full_chat.migrated_from_chat_id = None
    full_chan1.full_chat.hidden_prehistory = False

    invite_sg1 = MagicMock(link="https://t.me/+private_community_invite")

    async def mock_mtproto_dispatcher(req):
        if isinstance(req, GetDialogsRequest):
            return dialogs_mock
        if isinstance(req, GetFullChannelRequest):
            if req.channel == supergroup1 or getattr(req.channel, "id", None) == 20202:
                return full_sg1
            if req.channel == supergroup2 or getattr(req.channel, "id", None) == 40404:
                return full_sg2
            return full_chan1
        if isinstance(req, ExportChatInviteRequest):
            return invite_sg1
        return None

    mock_client.side_effect = mock_mtproto_dispatcher
    mock_client.get_messages = AsyncMock(return_value=[])

    session_manager.get_client = AsyncMock(return_value=mock_client)
    session_manager._clients[phone_target] = mock_client

    context = make_e2e_context(bot_data=app.bot_data)

    # 1. User triggers list_chats_{phone}
    update_chats = make_e2e_callback_update(f"list_chats_{phone_target}", user_id=user_id)
    res_chats = await list_chats_callback(update_chats, context)
    assert res_chats == ACCOUNT_ACTIONS

    chats_text = update_chats.callback_query.edit_message_text.call_args[1]["text"]

    # Verify creator chats inventory formatting
    assert "Official Crypto News" in chats_text
    assert "https://t.me/cryptonews_hq" in chats_text
    assert "Crypto Community Supergroup" in chats_text
    assert "https://t.me/+private_community_invite" in chats_text
    assert "Public Builders Supergroup" in chats_text

    # Deduplication verification:
    # Basic Chat 30303 was migrated to supergroup1 -> MUST BE OMITTED!
    assert "Old Basic Team Chat" not in chats_text

    # Non-creator chat 99999 MUST BE EXCLUDED!
    assert "Someone Else Channel" not in chats_text

    # History visibility verification:
    assert "Hidden" in chats_text or "پنهان" in chats_text
    assert "Visible" in chats_text or "نمایان" in chats_text

    # 2. User triggers get_code_{phone} with official 5-digit verification code from 777000
    msg_code = MagicMock()
    msg_code.message = "Login code: 82941. Do not give this code to anyone, even if they claim to be from Telegram!"
    msg_other = MagicMock()
    msg_other.message = "Your Telegram account was logged in from a new device."

    mock_client.side_effect = None
    mock_client.get_messages = AsyncMock(return_value=[msg_code, msg_other])

    update_code = make_e2e_callback_update(f"get_code_{phone_target}", user_id=user_id)
    res_code = await get_code_callback(update_code, context)
    assert res_code == ACCOUNT_ACTIONS

    code_text = update_code.callback_query.edit_message_text.call_args[1]["text"]
    assert "82941" in code_text, "5-digit code 82941 not found in format_latest_code response."

    # 3. Adversarial: User triggers get_code_{phone} when peer 777000 has no verification code
    mock_client.get_messages = AsyncMock(return_value=[msg_other])
    update_no_code = make_e2e_callback_update(f"get_code_{phone_target}", user_id=user_id)
    res_no_code = await get_code_callback(update_no_code, context)
    assert res_no_code == ACCOUNT_ACTIONS

    no_code_text = update_no_code.callback_query.edit_message_text.call_args[1]["text"]
    assert "No recent code messages found" in no_code_text
    assert phone_target in no_code_text

    await app.post_shutdown(app)


# ============================================================================
# Scenario 4: Safe Application Shutdown & Windows Resource Hygiene
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_4_safe_application_shutdown_and_windows_resource_hygiene(
    tmp_path: Path,
) -> None:
    """
    Tier 4 E2E Scenario 4:
    1. Full lifecycle bootstrap (build_application).
    2. Register multiple active clients in session manager.
    3. Invoke app.shutdown() and app.post_shutdown().
    4. Verify post_shutdown executes session_manager.disconnect_all() and db.close().
    5. Windows Resource Hygiene:
       - Confirms all open file handles are completely closed.
       - Confirms zero WinError 32 (PermissionError) when deleting session files
         and the database file on Windows.
    """
    db_path = tmp_path / "bot_e2e_s4.db"
    sessions_dir = tmp_path / "sessions_s4"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        api_id=11223,
        api_hash="mock_api_hash_s4",
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        database_path=db_path,
        sessions_dir=sessions_dir,
    )

    db_conn = DatabaseConnection(settings.database_path)
    session_manager = TelethonSessionManager(settings=settings)

    app = build_application(
        settings=settings,
        db_conn=db_conn,
        session_manager=session_manager,
    )

    # 1. Initialize DB and post_init
    await app.post_init(app)
    assert db_path.is_file(), "SQLite database file was not created on disk."
    await db_conn.connect()
    assert db_conn._shared_conn is not None

    # 2. Register 3 active clients in session_manager connection pool
    phones = ["+15156723851", "+15156723852", "+15156723853"]
    client_mocks = []

    for phone in phones:
        # Create physical .session file on disk
        session_file = sessions_dir / f"{phone}.session"
        session_file.write_bytes(f"SESSION_DATA_FOR_{phone}".encode("utf-8"))

        mock_client = MagicMock()
        mock_client.disconnect = AsyncMock()
        mock_client.session = MagicMock()
        mock_client.session.close = MagicMock()

        session_manager._clients[phone] = mock_client
        client_mocks.append(mock_client)

    assert len(session_manager.get_active_phones()) == 3

    # 3. Invoke post_shutdown lifecycle hook
    await app.post_shutdown(app)

    # 4. Verifications:
    # Disconnect must be invoked on all pooled clients
    for mock_client in client_mocks:
        mock_client.disconnect.assert_awaited_once()
        mock_client.session.close.assert_called_once()

    # Session pool must be completely empty
    assert len(session_manager.get_active_phones()) == 0

    # Database connection must be closed
    assert db_conn._shared_conn is None

    # 5. Windows Resource Hygiene & File Lock Proof:
    # Attempting to delete or unlink files that have lingering SQLite or socket
    # handles on Windows raises PermissionError: [WinError 32] The process cannot
    # access the file because it is being used by another process.
    for phone in phones:
        session_file = sessions_dir / f"{phone}.session"
        assert session_file.exists()
        # Must unlink cleanly without PermissionError / WinError 32
        session_file.unlink()
        assert not session_file.exists()

    # Database file itself must unlink cleanly without WinError 32
    assert db_path.exists()
    db_path.unlink()
    assert not db_path.exists()

    # Any SQLite WAL and SHM journal files must also unlink cleanly if present
    wal_file = db_path.with_name(f"{db_path.name}-wal")
    if wal_file.exists():
        wal_file.unlink()
    shm_file = db_path.with_name(f"{db_path.name}-shm")
    if shm_file.exists():
        shm_file.unlink()


# ============================================================================
# Scenario 5: Universal Re-Entry & State Reset Across All Conversation States
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_5_universal_reentry_across_all_conversation_states() -> None:
    """
    Tier 4 E2E Scenario 5:
    Universal navigation resilience:
    - User sending /start or /cancel during ANY state (PHONE, CODE, WAITING_FOR_CODE,
      or ACCOUNT_ACTIONS) immediately aborts pending authentication, disconnects
      pending clients, cleans up bot_data['pending_auth'], and returns ConversationHandler.END.
    """
    db = DatabaseConnection(":memory:")
    await db.init_db()
    user_repo = UserRepository(db)

    user_id = 555005
    pending_client = MagicMock()
    pending_client.disconnect = AsyncMock()

    context = make_e2e_context(
        bot_data={
            "user_repo": user_repo,
            "pending_auth": {user_id: {"client": pending_client, "phone": "+15156723850"}},
        },
        user_data={"current_phone": "+15156723850", "awaiting_2fa": True},
    )

    # 1. Issue /start while in pending state
    update_start = make_e2e_message_update("/start", user_id=user_id)
    res_start = await start(update_start, context)
    assert res_start == ConversationHandler.END

    pending_client.disconnect.assert_awaited_once()
    assert user_id not in context.bot_data["pending_auth"]

    # 2. Reset pending state and issue /cancel
    pending_client_2 = MagicMock()
    pending_client_2.disconnect = AsyncMock()
    context.bot_data["pending_auth"][user_id] = {
        "client": pending_client_2,
        "phone": "+15156723850",
    }

    update_cancel = make_e2e_message_update("/cancel", user_id=user_id)
    res_cancel = await cancel(update_cancel, context)
    assert res_cancel == ConversationHandler.END

    pending_client_2.disconnect.assert_awaited_once()
    assert user_id not in context.bot_data["pending_auth"]
    update_cancel.message.reply_text.assert_awaited_once()
    assert "Operation cancelled" in update_cancel.message.reply_text.call_args[1]["text"]

    await db.close()
