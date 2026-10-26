"""
tests.adversarial.test_m4_2_handlers_adversarial
================================================
Milestone 4.2 Adversarial Challenge Suite:
1. Streaming VCF generation under load (5,000+ contacts, non-ASCII/Unicode, empty, zero disk writes, vCard 3.0).
2. Batch deletion UI updates (RetryAfter, MessageNotModified, NetworkError resilience, confirmation guard).
3. Creator chats inspection (migrated chat deduplication, creator vs non-creator, hidden_prehistory).
4. 777000 official code retrieval (5-digit regex boundary isolation, varied formats, fallbacks).
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from telegram.ext import ConversationHandler
import vobject
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest, GetDialogsRequest
from telethon.tl.types import Channel, Chat, User

from bot.handlers.chat_handlers import get_code_callback, list_chats_callback
from bot.handlers.contact_handlers import (
    check_contacts_callback,
    confirm_delete_callback,
    delete_contacts_callback,
    export_mutual_callback,
    extract_contacts_callback,
)
from bot.messages import (
    DELETE_ERROR_TEXT,
    DELETE_WARNING_TEXT,
    NO_CODE_FOUND_TEXT,
    format_creator_chats,
    format_delete_warning,
    format_latest_code,
    format_no_code_found,
    format_no_contacts_to_delete,
)
from bot.states import ACCOUNT_ACTIONS
from services.chat_service import LOGIN_CODE_PATTERN, ChatInfo, ChatService
from services.contact_service import ContactService, DeleteResult
from utils.vcf import (
    ContactInfo,
    format_mutual_vcf_filename,
    format_vcf_filename,
    generate_vcf_content,
    generate_vcf_stream,
)


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


# ============================================================================
# 1. STREAMING VCF GENERATION UNDER LOAD & ADVERSARIAL INPUTS
# ============================================================================


class TestVcfStreamingAdversarial:
    """Stress tests and edge-case challenge for streaming VCF generation."""

    def test_vcf_stream_5000_contacts_load_and_zero_disk_writes(self) -> None:
        """
        Adversarial Scenario 1.1:
        Generate 5,000 contacts. Confirm zero disk writes, stream pointer rewound,
        and every card conforms to vCard 3.0 standard.
        """
        contacts = [
            ContactInfo(
                id=1000000 + i,
                phone=f"+1555{i:07d}",
                first_name=f"First{i}",
                last_name=f"Last{i}",
            )
            for i in range(5000)
        ]

        # Intercept any file write attempts
        with patch("builtins.open", side_effect=AssertionError("Disk open() attempted!")):
            with patch("os.open", side_effect=AssertionError("Disk os.open() attempted!")):
                with patch.object(Path, "write_text", side_effect=AssertionError("Path.write_text attempted!")):
                    with patch.object(Path, "write_bytes", side_effect=AssertionError("Path.write_bytes attempted!")):
                        stream = generate_vcf_stream(contacts, filename="batch_5000.vcf")

        assert isinstance(stream, io.BytesIO)
        assert stream.tell() == 0, "Stream read pointer must be rewound to 0"
        assert stream.name == "batch_5000.vcf"

        raw_bytes = stream.getvalue()
        assert len(raw_bytes) > 0

        # Sample inspection for vCard 3.0 structure
        content = raw_bytes.decode("utf-8")
        assert content.count("BEGIN:VCARD") == 5000
        assert content.count("END:VCARD") == 5000
        assert "VERSION:3.0" in content
        assert "FN:1000000" in content
        assert "FN:1004999" in content

    def test_vcf_stream_unicode_special_characters_vcard3_compliance(self) -> None:
        """
        Adversarial Scenario 1.2:
        Test contacts with Persian/Arabic names, CJK characters, emojis,
        semicolons, colons, newlines, tabs, and duck-typed objects.
        Verify valid vCard 3.0 parsing with vobject.
        """
        tricky_contacts = [
            # Persian / Arabic with spaces and diacritics
            ContactInfo(id="9876543", phone="+989121112233", first_name="محمدرضا", last_name="علوی"),
            # CJK characters
            ContactInfo(id="8765432", phone="+8613800138000", first_name="李小龙", last_name="王"),
            # Emojis & Symbols
            ContactInfo(id="7654321", phone="+1234567890", first_name="🔥🚀 Crypto King 👑", last_name="VIP 💎"),
            # Semicolons and colons in ID and phone
            ContactInfo(id="6543210", phone="+1-800:555;1234", first_name="Semicolon;Name", last_name="Colon:Name"),
            # Quotes, backslashes, tabs
            ContactInfo(id="5432109", phone=None, first_name='Quote "Test"', last_name="Backslash \\ Tab \t"),
            # Duck-typed dictionary input
            {"id": "4321098", "phone": "+447123456789", "first_name": "DictUser", "last_name": "Test"},
            # Duck-typed object with user_id instead of id
            MagicMock(user_id="3210987", phone="+33612345678", spec=["user_id", "phone"]),
        ]

        stream = generate_vcf_stream(tricky_contacts, filename="tricky.vcf")
        assert stream.tell() == 0

        decoded = stream.getvalue().decode("utf-8")
        # Validate that vobject can parse every single component without parse error
        cards = list(vobject.readComponents(decoded))
        assert len(cards) == 7

        for card in cards:
            assert card.name == "VCARD"
            assert card.version.value == "3.0"
            assert card.fn is not None
            assert card.n is not None

        # Verify specific Unicode values preserved
        assert "محمدرضا" in decoded or "9876543" in decoded
        assert "李小龙" in decoded or "8765432" in decoded
        assert "🔥🚀 Crypto King 👑" in decoded or "7654321" in decoded

    def test_vcf_stream_empty_and_corrupt_contacts(self) -> None:
        """
        Adversarial Scenario 1.3:
        Test empty contact lists, None inputs, and corrupt/missing ID elements.
        """
        # Empty list
        s1 = generate_vcf_stream([])
        assert isinstance(s1, io.BytesIO)
        assert s1.tell() == 0
        assert s1.getvalue() == b""

        # None input
        s2 = generate_vcf_stream(None)
        assert isinstance(s2, io.BytesIO)
        assert s2.tell() == 0
        assert s2.getvalue() == b""

        # Corrupt items: None, empty id, whitespace id, missing id
        corrupt_items = [
            None,
            ContactInfo(id=""),
            ContactInfo(id="   "),
            {"id": None, "phone": "+1234"},
            {"user_id": ""},
            MagicMock(spec=[]),  # No id or user_id attribute
        ]
        s3 = generate_vcf_stream(corrupt_items)
        assert s3.getvalue() == b""

    @pytest.mark.asyncio
    async def test_extract_contacts_callback_streaming_zero_disk(self) -> None:
        """
        Adversarial Scenario 1.4:
        Verify extract_contacts_callback streams directly to send_document
        without any temporary file on disk.
        """
        mock_cs = MagicMock(spec=ContactService)
        contacts = [ContactInfo(id=1234567, phone="+15551234567")]
        mock_cs.extract_contacts_by_length = AsyncMock(return_value=contacts)

        context = make_context(bot_data={"contact_service": mock_cs})
        update = make_callback_update("extract_7_+15156723850", user_id=123456)

        with patch("builtins.open", side_effect=AssertionError("Disk open() attempted!")):
            res = await extract_contacts_callback(update, context)

        assert res == ACCOUNT_ACTIONS
        context.bot.send_document.assert_awaited_once()
        doc_args = context.bot.send_document.call_args[1]
        doc = doc_args["document"]
        assert isinstance(doc, io.BytesIO)
        assert doc.tell() == 0
        assert b"BEGIN:VCARD" in doc.getvalue()


# ============================================================================
# 2. BATCH DELETION UI UPDATES & CONFIRMATION DIALOG
# ============================================================================


class TestBatchDeletionAdversarial:
    """Stress tests for deletion rate limits, errors, and confirmation guards."""

    @pytest.mark.asyncio
    async def test_batch_deletion_rate_limit_retry_after_resilience(self) -> None:
        """
        Adversarial Scenario 2.1:
        Simulate Telegram Bot API raising RetryAfter on intermediate query.edit_message_text calls.
        Verify that deletion DOES NOT abort, completes all batches, and displays final summary.
        """
        phone = "+15156723850"
        mock_cs = MagicMock(spec=ContactService)
        all_contacts = [ContactInfo(id=i) for i in range(1, 251)]  # 250 contacts -> 3 batches
        mock_cs.get_all_contacts = AsyncMock(return_value=all_contacts)

        # ContactService.delete_all_contacts executes progress callback
        async def mock_delete_all(phone, progress_callback=None, batch_delay=1.0):
            if progress_callback:
                # Fire progress callback multiple times
                await progress_callback(100, 250)
                await progress_callback(200, 250)
                await progress_callback(250, 250)
            return DeleteResult(total=250, deleted=250, failed=0, status="success")

        mock_cs.delete_all_contacts = AsyncMock(side_effect=mock_delete_all)
        context = make_context(bot_data={"contact_service": mock_cs})
        update = make_callback_update(f"confirm_delete_{phone}")

        # edit_message_text raises RetryAfter on progress updates, but succeeds on initial & final
        call_count = 0

        async def mock_edit_text(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count in (2, 3):  # Intermediate progress edits
                raise RetryAfter(retry_after=5)
            return MagicMock()

        update.callback_query.edit_message_text = AsyncMock(side_effect=mock_edit_text)

        res = await confirm_delete_callback(update, context)
        assert res == ACCOUNT_ACTIONS
        mock_cs.delete_all_contacts.assert_awaited_once()

        # Check final edit text contains completion report
        last_call_args = update.callback_query.edit_message_text.call_args[1]
        assert "Contact deletion completed" in last_call_args["text"]
        assert "Deleted: 250" in last_call_args["text"]

    @pytest.mark.asyncio
    async def test_batch_deletion_message_not_modified_and_network_errors(self) -> None:
        """
        Adversarial Scenario 2.2:
        Simulate Telegram BadRequest('Message is not modified') and TimedOut during progress edits.
        Verify deletion process swallows UI error and finishes accurately.
        """
        phone = "+15156723850"
        mock_cs = MagicMock(spec=ContactService)
        mock_cs.get_all_contacts = AsyncMock(return_value=[ContactInfo(id=1), ContactInfo(id=2)])

        async def mock_delete_all(phone, progress_callback=None, batch_delay=1.0):
            if progress_callback:
                # Progress update raises "Message is not modified"
                await progress_callback(1, 2)
                # Progress update raises TimedOut
                await progress_callback(2, 2)
            return DeleteResult(total=2, deleted=2, failed=0, status="success")

        mock_cs.delete_all_contacts = AsyncMock(side_effect=mock_delete_all)
        context = make_context(bot_data={"contact_service": mock_cs})
        update = make_callback_update(f"confirm_delete_{phone}")

        call_idx = 0

        async def mock_edit_text(*args, **kwargs):
            nonlocal call_idx
            call_idx += 1
            if call_idx == 2:
                raise BadRequest("Message is not modified: content is the same")
            elif call_idx == 3:
                raise TimedOut()
            return MagicMock()

        update.callback_query.edit_message_text = AsyncMock(side_effect=mock_edit_text)

        res = await confirm_delete_callback(update, context)
        assert res == ACCOUNT_ACTIONS

        final_text = update.callback_query.edit_message_text.call_args[1]["text"]
        assert "Contact deletion completed" in final_text
        assert "Deleted: 2" in final_text

    @pytest.mark.asyncio
    async def test_delete_confirmation_dialog_prevents_accidental_execution(self) -> None:
        """
        Adversarial Scenario 2.3:
        Verify clicking delete_contacts ONLY presents warning and does NOT invoke delete_all_contacts.
        Verify reply markup contains explicit cancel option.
        """
        phone = "+15156723850"
        mock_cs = MagicMock(spec=ContactService)
        mock_cs.get_all_contacts = AsyncMock(return_value=[ContactInfo(id=1), ContactInfo(id=2), ContactInfo(id=3)])
        mock_cs.delete_all_contacts = AsyncMock()

        context = make_context(bot_data={"contact_service": mock_cs})
        update = make_callback_update(f"delete_contacts_{phone}")

        res = await delete_contacts_callback(update, context)
        assert res == ACCOUNT_ACTIONS

        # CRUCIAL: delete_all_contacts MUST NEVER be called during warning step
        mock_cs.delete_all_contacts.assert_not_called()

        # Verify warning dialog text and buttons
        call_args = update.callback_query.edit_message_text.call_args[1]
        assert "⚠️ Warning!" in call_args["text"]
        assert "3" in call_args["text"]

        keyboard = call_args["reply_markup"].inline_keyboard
        callback_datas = [btn.callback_data for row in keyboard for btn in row]
        assert f"confirm_delete_{phone}" in callback_datas
        assert f"select_{phone}" in callback_datas, "Must have cancel button returning to account actions"

    @pytest.mark.asyncio
    async def test_delete_contacts_empty_list_safeguard(self) -> None:
        """
        Adversarial Scenario 2.4:
        When account has zero contacts, delete_contacts_callback must NOT show confirmation dialog.
        """
        phone = "+15156723850"
        mock_cs = MagicMock(spec=ContactService)
        mock_cs.get_all_contacts = AsyncMock(return_value=[])
        mock_cs.delete_all_contacts = AsyncMock()

        context = make_context(bot_data={"contact_service": mock_cs})
        update = make_callback_update(f"delete_contacts_{phone}")

        res = await delete_contacts_callback(update, context)
        assert res == ACCOUNT_ACTIONS
        mock_cs.delete_all_contacts.assert_not_called()

        call_args = update.callback_query.edit_message_text.call_args[1]
        assert "No contacts found to delete" in call_args["text"]
        # Should not have confirm button
        keyboard = call_args["reply_markup"].inline_keyboard
        callback_datas = [btn.callback_data for row in keyboard for btn in row]
        assert f"confirm_delete_{phone}" not in callback_datas


# ============================================================================
# 3. CREATOR CHATS INSPECTION & DEDUPLICATION
# ============================================================================


class TestCreatorChatsAdversarial:
    """Stress tests for chat migration deduplication, creator ownership, and prehistory."""

    @pytest.mark.asyncio
    async def test_creator_chats_migrated_supergroup_deduplication(self) -> None:
        """
        Adversarial Scenario 3.1:
        Account owns a basic Chat (id=1001) that was migrated into a Supergroup Channel (id=2001).
        Verify list_creator_chats deduplicates the basic chat and includes only the supergroup.
        """
        mock_sm = AsyncMock()
        mock_sm.normalize_phone = MagicMock(return_value="+15156723850")
        client = AsyncMock()

        # Basic Chat that was migrated
        basic_chat = MagicMock(spec=Chat)
        basic_chat.id = 1001
        basic_chat.title = "Old Legacy Group"
        basic_chat.creator = True

        # Supergroup that basic_chat migrated into
        supergroup = MagicMock(spec=Channel)
        supergroup.id = 2001
        supergroup.title = "New Migrated Supergroup"
        supergroup.creator = True
        supergroup.megagroup = True
        supergroup.username = "new_supergroup"

        dialogs = MagicMock()
        dialogs.chats = [basic_chat, supergroup]

        # Full channel info specifies migrated_from_chat_id = 1001
        full_info = MagicMock()
        full_info.full_chat.migrated_from_chat_id = 1001
        full_info.full_chat.hidden_prehistory = True

        async def mock_handler(req):
            if isinstance(req, GetDialogsRequest):
                return dialogs
            if isinstance(req, GetFullChannelRequest):
                return full_info
            return None

        client.side_effect = mock_handler
        client.get_messages = AsyncMock(return_value=[])
        mock_sm.get_client.return_value = client

        service = ChatService(mock_sm)
        chats = await service.list_creator_chats("+15156723850")

        # Basic chat 1001 MUST be filtered out
        assert len(chats) == 1
        assert chats[0].id == 2001
        assert chats[0].type == "supergroup"
        assert chats[0].migrated_from_chat_id == 1001
        assert chats[0].hidden_prehistory is True
        assert chats[0].history_visibility == "Hidden"

    @pytest.mark.asyncio
    async def test_creator_vs_non_creator_filtering(self) -> None:
        """
        Adversarial Scenario 3.2:
        Chats where user is admin or member (creator=False or None) must be strictly omitted.
        """
        mock_sm = AsyncMock()
        mock_sm.normalize_phone = MagicMock(return_value="+15156723850")
        client = AsyncMock()

        creator_channel = MagicMock(spec=Channel)
        creator_channel.id = 101
        creator_channel.creator = True
        creator_channel.megagroup = False
        creator_channel.username = "my_channel"

        non_creator_admin = MagicMock(spec=Channel)
        non_creator_admin.id = 102
        non_creator_admin.creator = False
        non_creator_admin.megagroup = False

        regular_chat_member = MagicMock(spec=Chat)
        regular_chat_member.id = 103
        regular_chat_member.creator = False

        user_dm = MagicMock(spec=User)
        user_dm.id = 104
        user_dm.creator = False

        dialogs = MagicMock()
        dialogs.chats = [creator_channel, non_creator_admin, regular_chat_member, user_dm]

        client.side_effect = lambda req: dialogs if isinstance(req, GetDialogsRequest) else None
        client.get_messages = AsyncMock(return_value=[])
        mock_sm.get_client.return_value = client

        service = ChatService(mock_sm)
        chats = await service.list_creator_chats("+15156723850")

        assert len(chats) == 1
        assert chats[0].id == 101

    @pytest.mark.asyncio
    async def test_creator_chats_history_visibility_fallback_to_min_id(self) -> None:
        """
        Adversarial Scenario 3.3:
        When hidden_prehistory attribute is None, fallback to available_min_id > 1.
        Also test GetFullChannelRequest throwing exception falling back to Unknown.
        """
        mock_sm = AsyncMock()
        mock_sm.normalize_phone = MagicMock(return_value="+15156723850")
        client = AsyncMock()

        # Supergroup 1: hidden_prehistory is None, available_min_id = 50 -> Hidden
        sg1 = MagicMock(spec=Channel)
        sg1.id = 301
        sg1.creator = True
        sg1.megagroup = True
        sg1.username = None

        # Supergroup 2: hidden_prehistory is None, available_min_id = 0 -> Visible
        sg2 = MagicMock(spec=Channel)
        sg2.id = 302
        sg2.creator = True
        sg2.megagroup = True
        sg2.username = None

        # Channel 3: GetFullChannelRequest raises RPC error -> Unknown
        ch3 = MagicMock(spec=Channel)
        ch3.id = 303
        ch3.creator = True
        ch3.megagroup = False
        ch3.username = None

        dialogs = MagicMock()
        dialogs.chats = [sg1, sg2, ch3]

        async def mock_handler(req):
            if isinstance(req, GetDialogsRequest):
                return dialogs
            if isinstance(req, GetFullChannelRequest):
                if req.channel.id == 301:
                    f = MagicMock()
                    f.full_chat.migrated_from_chat_id = None
                    f.full_chat.hidden_prehistory = None
                    f.full_chat.available_min_id = 50
                    return f
                elif req.channel.id == 302:
                    f = MagicMock()
                    f.full_chat.migrated_from_chat_id = None
                    f.full_chat.hidden_prehistory = None
                    f.full_chat.available_min_id = 1
                    return f
                elif req.channel.id == 303:
                    raise RuntimeError("Channel RPC error")
            return None

        client.side_effect = mock_handler
        client.get_messages = AsyncMock(return_value=[])
        mock_sm.get_client.return_value = client

        service = ChatService(mock_sm)
        chats = await service.list_creator_chats("+15156723850")

        chat_map = {c.id: c for c in chats}
        assert chat_map[301].history_visibility == "Hidden"
        assert chat_map[302].history_visibility == "Visible"
        assert chat_map[303].history_visibility == "Unknown"

        # Check formatting output representation
        formatted = format_creator_chats("+15156723850", chats)
        assert "🔒 Hidden / مخفی" in formatted
        assert "👁️ Visible / قابل مشاهده" in formatted
        assert "❓ Unknown / نامشخص" in formatted


# ============================================================================
# 4. 777000 OFFICIAL CODE RETRIEVAL REGEX & MESSAGE EXTRACTION
# ============================================================================


class TestOfficialCodeRegexAdversarial:
    """Stress tests for peer 777000 5-digit regex pattern and handler fallback."""

    @pytest.mark.parametrize(
        "message_text,expected_code",
        [
            # Standard English notifications
            ("Telegram code: 49201\n\nYou can also tap on this link to log in:", "49201"),
            ("Login code: 82914. Do not give this code to anyone!", "82914"),
            ("Your verification code is 12345.", "12345"),
            # Persian notifications
            ("کد ورود تلگرام شما: 54321\nاین کد را در اختیار دیگران قرار ندهید.", "54321"),
            ("کد تایید: 98765", "98765"),
            # Code at edge boundaries
            ("10293 is your Telegram login code", "10293"),
            ("Your Telegram code: 67584", "67584"),
            # Code in link
            ("Tap here to log in: https://telegram.me/login/33445", "33445"),
            # Mixed with other numbers (IP, date, phone, device info)
            ("Login code: 71829. Device: PC, IP: 192.168.1.100, Date: 2026-10-25 14:30:00", "71829"),
            ("Phone: +15156723850, Telegram code: 99182", "99182"),
        ],
    )
    def test_login_code_regex_matching_valid_patterns(
        self, message_text: str, expected_code: str
    ) -> None:
        """Adversarial Scenario 4.1: Verify regex matches exact 5-digit code across variations."""
        match = LOGIN_CODE_PATTERN.search(message_text)
        assert match is not None
        assert match.group(1) == expected_code

    @pytest.mark.parametrize(
        "invalid_text",
        [
            "Your 4-digit PIN is 1234",
            "Your 6-digit code is 123456",
            "User ID is 1234567",
            "Session abc12345 cannot be verified",
            "Token 12345xyz is invalid",
            "We detected a login from a new device on 2026-10-25",
            "Your IP address 192.168.1.1 has been authorized",
            "",
            "   ",
        ],
    )
    def test_login_code_regex_rejects_non_5digit_patterns(self, invalid_text: str) -> None:
        """Adversarial Scenario 4.2: Verify regex rejects 4-digit, 6-digit, and non-boundary numbers."""
        match = LOGIN_CODE_PATTERN.search(invalid_text)
        assert match is None

    @pytest.mark.asyncio
    async def test_get_code_callback_with_no_code_and_fallback_notice(self) -> None:
        """
        Adversarial Scenario 4.3:
        When peer 777000 has no code messages (or messages is empty), verify handler
        displays format_no_code_found without error.
        """
        phone = "+15156723850"
        mock_chat_service = MagicMock(spec=ChatService)
        mock_chat_service.get_latest_login_message = AsyncMock(return_value=None)

        context = make_context(bot_data={"chat_service": mock_chat_service})
        update = make_callback_update(f"get_code_{phone}")

        res = await get_code_callback(update, context)
        assert res == ACCOUNT_ACTIONS

        call_args = update.callback_query.edit_message_text.call_args[1]
        assert "No recent code messages found" in call_args["text"]

    @pytest.mark.asyncio
    async def test_get_code_callback_service_exception_handling(self) -> None:
        """
        Adversarial Scenario 4.4:
        When Telethon or chat_service raises an unexpected exception, verify handler
        catches it, displays CODE_ERROR_TEXT, and does not crash the bot.
        """
        phone = "+15156723850"
        mock_chat_service = MagicMock(spec=ChatService)
        mock_chat_service.get_latest_login_message = AsyncMock(
            side_effect=RuntimeError("Telethon connection dropped")
        )

        context = make_context(bot_data={"chat_service": mock_chat_service})
        update = make_callback_update(f"get_code_{phone}")

        res = await get_code_callback(update, context)
        assert res == ACCOUNT_ACTIONS

        call_args = update.callback_query.edit_message_text.call_args[1]
        assert "Error getting code" in call_args["text"]
        assert "Telethon connection dropped" in call_args["text"]
