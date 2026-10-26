"""
tests.services.test_adversarial_m3_2
====================================
Adversarial stress-testing suite for Telethon Core Services (Milestone M3.2).

Covers:
1. 2FA Password flows (malformed passwords, empty/whitespace, unicode, repeated attempts, unexpected RPC errors).
2. Contact extraction edge cases (extreme lengths, non-integer IDs, empty lists, 10,000+ contacts benchmark).
3. Batch contact deletion (chunking by 100, partial failures, progress callback exceptions, FloodWaitError simulation).
4. Dialogs listing and 777000 regex evasion (circular migration, missing full info, export link failures, regex edge cases).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    RPCError,
    SessionPasswordNeededError,
)
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.contacts import DeleteContactsRequest, GetContactsRequest
from telethon.tl.functions.messages import ExportChatInviteRequest, GetDialogsRequest
from telethon.tl.types import Channel, Chat, InputPeerEmpty, User

from services.auth_service import AuthService, SignInResult
from services.chat_service import LOGIN_CODE_PATTERN, ChatInfo, ChatService
from services.contact_service import ContactInfo, ContactService, DeleteResult
from services.session_manager import TelethonSessionManager


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def mock_session_manager() -> AsyncMock:
    """Provide a mock TelethonSessionManager."""
    sm = AsyncMock(spec=TelethonSessionManager)
    sm.normalize_phone = lambda p: p if p.startswith("+") else f"+{p.strip()}"
    return sm


def make_mock_user(
    uid: Any,
    phone: Optional[str] = None,
    first_name: Optional[str] = "User",
    last_name: Optional[str] = "Test",
    mutual_contact: bool = False,
) -> MagicMock:
    """Helper to create duck-typed Telethon User mock."""
    u = MagicMock(spec=User)
    u.id = uid
    u.phone = phone
    u.first_name = first_name
    u.last_name = last_name
    u.mutual_contact = mutual_contact
    return u


def make_mock_contact(user_id: Any, mutual: bool = False) -> MagicMock:
    """Helper to create duck-typed Telethon Contact mock."""
    c = MagicMock()
    c.user_id = user_id
    c.mutual = mutual
    return c


# ==============================================================================
# 1. 2FA Password Flow Adversarial Tests
# ==============================================================================

class Test2FAPasswordFlows:
    """Adversarial stress-testing of 2FA password handling in AuthService."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "password_input, expected_status",
        [
            ("", "invalid_password"),
            ("   \t\n  ", "invalid_password"),
            ("🔐🔑P@ssw0rd™_مرحبا", "success"),
            ("A" * 5000, "invalid_password"),  # Extremely long password
        ],
    )
    async def test_2fa_passwords_malformed_and_boundary(
        self,
        mock_session_manager: AsyncMock,
        password_input: str,
        expected_status: str,
    ) -> None:
        """Verify handling of empty, whitespace, unicode, and extreme length 2FA passwords."""
        client = AsyncMock()
        mock_session_manager.get_client.return_value = client

        if expected_status == "invalid_password":
            client.sign_in.side_effect = PasswordHashInvalidError(request=None)
        else:
            me = MagicMock()
            me.id = 9999999
            me.first_name = "Auth"
            me.last_name = "User"
            me.username = "authuser"
            client.get_me.return_value = me

        service = AuthService(mock_session_manager)
        result = await service.sign_in_2fa("+15156723850", password_input)

        assert result.status == expected_status
        assert result.phone == "+15156723850"
        client.sign_in.assert_awaited_once_with(password=password_input)

    @pytest.mark.asyncio
    async def test_2fa_repeated_attempts_retains_hash(
        self, mock_session_manager: AsyncMock
    ) -> None:
        """
        Verify that multiple sequential failed 2FA attempts do not invalidate or
        prematurely clear cached phone_code_hash until a successful login occurs.
        """
        client = AsyncMock()
        mock_session_manager.get_client.return_value = client

        # 2 failures followed by 1 success
        me = MagicMock()
        me.id = 1234567
        me.first_name = "Success"
        me.last_name = None
        me.username = None

        client.sign_in.side_effect = [
            PasswordHashInvalidError(request=None),
            PasswordHashInvalidError(request=None),
            me,
        ]
        client.get_me.return_value = me

        service = AuthService(mock_session_manager)
        phone = "+15156723850"
        service.set_cached_hash(phone, "cached_hash_12345")

        # Attempt 1: Wrong password
        r1 = await service.sign_in_2fa(phone, "wrong_pass_1")
        assert r1.status == "invalid_password"
        assert service.get_cached_hash(phone) == "cached_hash_12345"

        # Attempt 2: Wrong password
        r2 = await service.sign_in_2fa(phone, "wrong_pass_2")
        assert r2.status == "invalid_password"
        assert service.get_cached_hash(phone) == "cached_hash_12345"

        # Attempt 3: Correct password
        r3 = await service.sign_in_2fa(phone, "correct_pass")
        assert r3.status == "success"
        assert r3.user_id == 1234567
        # Hash cleared only after success
        assert service.get_cached_hash(phone) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "rpc_exception, expected_status",
        [
            (FloodWaitError(request=None), "flood_wait"),
            (RPCError(request=None, code=400, message="PASSWORD_EMPTY"), "error"),
            (ConnectionResetError("Socket reset by peer"), "error"),
            (asyncio.TimeoutError(), "error"),
            (PhoneNumberBannedError(request=None), "banned"),
            (SessionPasswordNeededError(request=None), "2fa_required"),
        ],
    )
    async def test_2fa_unexpected_rpc_and_network_errors(
        self,
        mock_session_manager: AsyncMock,
        rpc_exception: Exception,
        expected_status: str,
    ) -> None:
        """Verify all unexpected MTProto and network exceptions during 2FA are safely trapped."""
        client = AsyncMock()
        if isinstance(rpc_exception, FloodWaitError):
            rpc_exception.seconds = 120
        client.sign_in.side_effect = rpc_exception
        mock_session_manager.get_client.return_value = client

        service = AuthService(mock_session_manager)
        result = await service.sign_in_2fa("+15156723850", "some_password")

        assert result.status == expected_status
        if expected_status == "flood_wait":
            assert result.wait_seconds == 120


# ==============================================================================
# 2. Contact Extraction Edge Cases & Scale Tests
# ==============================================================================

class TestContactExtractionEdgeCases:
    """Adversarial stress-testing of contact extraction, filtering, and scaling."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "extreme_length",
        [
            0,
            -1,
            -10,
            16,
            100,
            "0",
            "-5",
            "100",
            "invalid_spec",
            "0to9",
            "7to25",
            None,
        ],
    )
    async def test_extract_contacts_extreme_and_invalid_lengths(
        self, mock_session_manager: AsyncMock, extreme_length: Any
    ) -> None:
        """Verify extreme and illegal digit lengths raise ValueError."""
        client = AsyncMock()
        res = MagicMock()
        res.users = [make_mock_user(1234567)]
        res.contacts = [make_mock_contact(1234567)]
        client.side_effect = lambda req: res if isinstance(req, GetContactsRequest) else None
        mock_session_manager.get_client.return_value = client

        service = ContactService(mock_session_manager)
        with pytest.raises(ValueError):
            await service.extract_contacts_by_length("+15156723850", extreme_length)

    @pytest.mark.asyncio
    async def test_extract_contacts_non_integer_and_malformed_ids(
        self, mock_session_manager: AsyncMock
    ) -> None:
        """
        Adversarially inject malformed, negative, string, float, and None user IDs.
        Verify that negative (channel IDs), non-numeric, None, and zero are rejected,
        while string-encoded valid positive integers are correctly parsed.
        """
        client = AsyncMock()
        raw_users = [
            make_mock_user(None),                     # None ID -> skipped
            make_mock_user(-1001234567),              # Negative channel ID -> filtered
            make_mock_user(0),                        # 0 -> filtered
            make_mock_user("not_a_number"),           # Non-numeric string -> filtered
            make_mock_user("1234567"),                # Numeric string -> parsed as 7 digits
            make_mock_user(87654321),                 # 8 digits
            {"id": "987654321", "is_mutual": True},   # Dict 9 digits
            {"user_id": -555, "first_name": "Bad"},   # Negative dict -> filtered
            {"id": None},                             # Empty dict -> skipped
        ]
        res = MagicMock()
        res.users = raw_users
        res.contacts = []

        client.side_effect = lambda req: res if isinstance(req, GetContactsRequest) else None
        mock_session_manager.get_client.return_value = client

        service = ContactService(mock_session_manager)
        contacts_7 = await service.extract_contacts_by_length("+15156723850", 7)
        contacts_8 = await service.extract_contacts_by_length("+15156723850", 8)
        contacts_9 = await service.extract_contacts_by_length("+15156723850", 9)

        assert len(contacts_7) == 1
        assert str(contacts_7[0].id) == "1234567"

        assert len(contacts_8) == 1
        assert contacts_8[0].id == 87654321

        assert len(contacts_9) == 1
        assert str(contacts_9[0].id) == "987654321"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "empty_payload",
        [
            MagicMock(users=[], contacts=[]),
            MagicMock(users=None, contacts=None),
            [],
        ],
    )
    async def test_extract_contacts_empty_payloads(
        self, mock_session_manager: AsyncMock, empty_payload: Any
    ) -> None:
        """Verify empty responses or None payloads return empty lists gracefully."""
        client = AsyncMock()
        client.side_effect = lambda req: empty_payload if isinstance(req, GetContactsRequest) else None
        mock_session_manager.get_client.return_value = client

        service = ContactService(mock_session_manager)
        all_c = await service.get_all_contacts("+15156723850")
        assert all_c == []

        filtered = await service.extract_contacts_by_length("+15156723850", 7)
        assert filtered == []

        summary = await service.get_contacts_summary("+15156723850")
        assert summary["total"] == 0
        assert summary["mutual"] == 0

    @pytest.mark.asyncio
    async def test_massive_contact_list_benchmark(
        self, mock_session_manager: AsyncMock
    ) -> None:
        """
        Stress-test contact extraction with 10,000 contacts.
        Measures CPU runtime to ensure sub-second completion and memory stability.
        """
        client = AsyncMock()

        # Generate 10,000 synthetic contacts
        # 3,000 x 7 digits, 3,000 x 8 digits, 3,000 x 9 digits, 1,000 x 10 digits
        users = []
        contacts = []
        for i in range(3000):
            uid = 1000000 + i
            users.append(make_mock_user(uid, mutual_contact=(i % 2 == 0)))
            contacts.append(make_mock_contact(uid, mutual=(i % 2 == 0)))
        for i in range(3000):
            uid = 10000000 + i
            users.append(make_mock_user(uid, mutual_contact=False))
            contacts.append(make_mock_contact(uid, mutual=False))
        for i in range(3000):
            uid = 100000000 + i
            users.append(make_mock_user(uid, mutual_contact=False))
            contacts.append(make_mock_contact(uid, mutual=False))
        for i in range(1000):
            uid = 1000000000 + i
            users.append(make_mock_user(uid, mutual_contact=False))
            contacts.append(make_mock_contact(uid, mutual=False))

        res = MagicMock()
        res.users = users
        res.contacts = contacts
        client.side_effect = lambda req: res if isinstance(req, GetContactsRequest) else None
        mock_session_manager.get_client.return_value = client

        service = ContactService(mock_session_manager)

        start_time = time.perf_counter()
        summary = await service.get_contacts_summary("+15156723850")
        elapsed = time.perf_counter() - start_time

        assert summary["total"] == 10000
        assert summary["mutual"] == 1500
        assert summary["breakdown"][7] == 3000
        assert summary["breakdown"][8] == 3000
        assert summary["breakdown"][9] == 3000
        assert summary["breakdown"][10] == 1000
        # Scale performance: must finish under 1.5 seconds on modern hardware
        assert elapsed < 1.5, f"10k contacts took too long: {elapsed:.3f}s"


# ==============================================================================
# 3. Batch Contact Deletion Adversarial Tests
# ==============================================================================

class TestBatchContactDeletionAdversarial:
    """Adversarial stress-testing of contact deletion chunking, rate-limiting, and errors."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "total_count, expected_batch_sizes",
        [
            (0, []),
            (1, [1]),
            (99, [99]),
            (100, [100]),
            (101, [100, 1]),
            (200, [100, 100]),
            (355, [100, 100, 100, 55]),
            (1000, [100] * 10),
        ],
    )
    async def test_exact_chunking_100_boundaries(
        self,
        mock_session_manager: AsyncMock,
        total_count: int,
        expected_batch_sizes: list[int],
    ) -> None:
        """Verify strict chunking to max 100 contacts across all boundary values."""
        client = AsyncMock()
        users = [make_mock_user(2000000 + i) for i in range(total_count)]
        res = MagicMock()
        res.users = users
        res.contacts = []

        recorded_batches: list[list[int]] = []

        async def handler(req: Any) -> Any:
            if isinstance(req, GetContactsRequest):
                return res
            if isinstance(req, DeleteContactsRequest):
                recorded_batches.append(req.id)
                return True
            return None

        client.side_effect = handler
        mock_session_manager.get_client.return_value = client

        service = ContactService(mock_session_manager)
        result = await service.delete_all_contacts("+15156723850", batch_delay=0.0)

        assert result.total == total_count
        assert result.deleted == total_count
        assert result.failed == 0
        assert [len(b) for b in recorded_batches] == expected_batch_sizes

    @pytest.mark.asyncio
    async def test_deletion_partial_failure_distribution(
        self, mock_session_manager: AsyncMock
    ) -> None:
        """Verify partial failure correctly accounts deleted vs failed counts across 5 batches."""
        client = AsyncMock()
        # 500 contacts -> 5 batches
        users = [make_mock_user(3000000 + i) for i in range(500)]
        res = MagicMock()
        res.users = users
        res.contacts = []

        call_idx = 0

        async def handler(req: Any) -> Any:
            nonlocal call_idx
            if isinstance(req, GetContactsRequest):
                return res
            if isinstance(req, DeleteContactsRequest):
                call_idx += 1
                # Batches 2 and 4 fail; batches 1, 3, 5 succeed
                if call_idx in (2, 4):
                    raise RuntimeError(f"Network error on batch {call_idx}")
                return True
            return None

        client.side_effect = handler
        mock_session_manager.get_client.return_value = client

        service = ContactService(mock_session_manager)
        result = await service.delete_all_contacts("+15156723850", batch_delay=0.0)

        assert result.total == 500
        assert result.deleted == 300
        assert result.failed == 200
        assert result.status == "partial"

    @pytest.mark.asyncio
    async def test_deletion_all_batches_fail(
        self, mock_session_manager: AsyncMock
    ) -> None:
        """Verify status is 'failed' when all batches encounter errors."""
        client = AsyncMock()
        users = [make_mock_user(3000000 + i) for i in range(150)]
        res = MagicMock()
        res.users = users
        res.contacts = []

        async def handler(req: Any) -> Any:
            if isinstance(req, GetContactsRequest):
                return res
            if isinstance(req, DeleteContactsRequest):
                raise RuntimeError("Total failure")
            return None

        client.side_effect = handler
        mock_session_manager.get_client.return_value = client

        service = ContactService(mock_session_manager)
        result = await service.delete_all_contacts("+15156723850", batch_delay=0.0)

        assert result.total == 150
        assert result.deleted == 0
        assert result.failed == 150
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_deletion_progress_callback_robustness(
        self, mock_session_manager: AsyncMock
    ) -> None:
        """
        Verify progress_callback exceptions (sync or async) do NOT abort the deletion loop
        and do NOT corrupt final result.
        """
        client = AsyncMock()
        users = [make_mock_user(4000000 + i) for i in range(300)]
        res = MagicMock()
        res.users = users
        res.contacts = []
        client.side_effect = lambda req: res if isinstance(req, GetContactsRequest) else True
        mock_session_manager.get_client.return_value = client

        invocations: list[tuple[int, int]] = []

        async def faulty_callback(deleted: int, total: int) -> None:
            invocations.append((deleted, total))
            # Raise exception on every second callback
            if len(invocations) % 2 == 1:
                raise RuntimeError("UI TelegramError simulation in callback")

        service = ContactService(mock_session_manager)
        result = await service.delete_all_contacts(
            "+15156723850", progress_callback=faulty_callback, batch_delay=0.0
        )

        assert result.status == "success"
        assert result.deleted == 300
        assert len(invocations) == 3

    @pytest.mark.asyncio
    async def test_deletion_flood_wait_behavior(
        self, mock_session_manager: AsyncMock
    ) -> None:
        """
        Examine how FloodWaitError is handled during batch contact deletion.
        Validates that FloodWaitError in DeleteContactsRequest does not cause an
        unhandled crash, but is recorded in failed_count.
        """
        client = AsyncMock()
        users = [make_mock_user(5000000 + i) for i in range(200)]
        res = MagicMock()
        res.users = users
        res.contacts = []

        call_count = 0

        async def handler(req: Any) -> Any:
            nonlocal call_count
            if isinstance(req, GetContactsRequest):
                return res
            if isinstance(req, DeleteContactsRequest):
                call_count += 1
                if call_count == 1:
                    fw = FloodWaitError(request=None)
                    fw.seconds = 5
                    raise fw
                return True
            return None

        client.side_effect = handler
        mock_session_manager.get_client.return_value = client

        service = ContactService(mock_session_manager)
        result = await service.delete_all_contacts("+15156723850", batch_delay=0.0)

        # Batch 1 raised FloodWaitError -> marked as failed (100)
        # Batch 2 succeeded -> marked as deleted (100)
        assert result.total == 200
        assert result.deleted == 100
        assert result.failed == 100
        assert result.status == "partial"


# ==============================================================================
# 4. Dialogs Listing & 777000 Code Regex Adversarial Tests
# ==============================================================================

class TestChatServiceAndLoginCodeRegex:
    """Adversarial stress-testing of ChatService dialog traversal and 777000 regex."""

    @pytest.mark.asyncio
    async def test_chat_listing_circular_migration_and_fallbacks(
        self, mock_session_manager: AsyncMock
    ) -> None:
        """
        Stress-test list_creator_chats with circular migration references,
        missing full channel info, and invite link export failures.
        """
        client = AsyncMock()

        # Chat 1: Megagroup Supergroup (id=1001, claims migrated from Chat 2001)
        sg1 = MagicMock(spec=Channel)
        sg1.id = 1001
        sg1.title = "Supergroup 1"
        sg1.megagroup = True
        sg1.creator = True
        sg1.username = None

        # Chat 2: Basic Chat (id=2001, creator=True) - should be deduplicated
        bc1 = MagicMock(spec=Chat)
        bc1.id = 2001
        bc1.title = "Basic Group Migrated"
        bc1.creator = True

        # Chat 3: Megagroup Supergroup (id=1002, creator=True, GetFullChannel fails)
        sg2 = MagicMock(spec=Channel)
        sg2.id = 1002
        sg2.title = "Supergroup Broken Full Info"
        sg2.megagroup = True
        sg2.creator = True
        sg2.username = None

        # Chat 4: Broadcast Channel (id=1003, username exists)
        ch1 = MagicMock(spec=Channel)
        ch1.id = 1003
        ch1.title = "Broadcast Channel"
        ch1.megagroup = False
        ch1.creator = True
        ch1.username = "broadcast_public"

        dialogs_res = MagicMock()
        dialogs_res.chats = [sg1, bc1, sg2, ch1]

        # Full channel responses
        full1 = MagicMock()
        full1.full_chat.migrated_from_chat_id = 2001
        full1.full_chat.hidden_prehistory = True

        async def handler(req: Any) -> Any:
            if isinstance(req, GetDialogsRequest):
                return dialogs_res
            if isinstance(req, GetFullChannelRequest):
                if req.channel.id == 1001:
                    return full1
                if req.channel.id == 1002:
                    raise RPCError(request=None, code=400, message="CHANNEL_PRIVATE")
            if isinstance(req, ExportChatInviteRequest):
                # Fail export to test fallback link
                raise RPCError(request=None, code=400, message="CHAT_ADMIN_REQUIRED")
            return None

        client.side_effect = handler
        # Creation date mock: fail to test graceful None
        client.get_messages.side_effect = RuntimeError("Message history unavailable")
        mock_session_manager.get_client.return_value = client

        service = ChatService(mock_session_manager)
        chats = await service.list_creator_chats("+15156723850")

        # bc1 (id=2001) should be filtered out!
        # Result should contain sg1 (1001), sg2 (1002), ch1 (1003)
        chat_ids = [c.id for c in chats]
        assert 2001 not in chat_ids
        assert chat_ids == [1001, 1002, 1003]

        # Verify fallback link when ExportChatInviteRequest fails
        sg1_info = next(c for c in chats if c.id == 1001)
        assert sg1_info.link == "https://t.me/c/1001"
        assert sg1_info.hidden_prehistory is True
        assert sg1_info.history_visibility == "Hidden"

        # Verify broken full channel info sets visibility to Unknown
        sg2_info = next(c for c in chats if c.id == 1002)
        assert sg2_info.history_visibility == "Unknown"
        assert sg2_info.link == "https://t.me/c/1002"

        # Verify public channel link
        ch1_info = next(c for c in chats if c.id == 1003)
        assert ch1_info.link == "https://t.me/broadcast_public"

    @pytest.mark.parametrize(
        "message_text, expected_code",
        [
            # Standard Telegram official login messages
            ("Telegram code: 49201. Do not give this code to anyone.", "49201"),
            ("Your login code is 83719. If you did not request it, ignore.", "83719"),
            ("Login code: 00123\nDevice: Web, IP: 1.2.3.4", "00123"),
            ("49201 is your Telegram code.", "49201"),
            # Messages that must NOT match
            ("Your verification code is 1234.", None),        # 4 digits
            ("Order number: 123456 has shipped.", None),      # 6 digits
            ("Phone number +15551234567 registered.", None),  # 11 digits
            ("Code is ABC12345XYZ", None),                    # alphanumeric attached
            ("", None),                                       # empty
            ("No numbers here at all!", None),
        ],
    )
    def test_777000_regex_patterns(
        self, message_text: str, expected_code: Optional[str]
    ) -> None:
        """Adversarially evaluate LOGIN_CODE_PATTERN on valid and invalid message formats."""
        match = LOGIN_CODE_PATTERN.search(message_text)
        if expected_code is None:
            assert match is None, f"Expected no match for: {message_text!r}, got {match.group(1)}"
        else:
            assert match is not None, f"Expected match for: {message_text!r}"
            assert match.group(1) == expected_code

    @pytest.mark.asyncio
    async def test_get_latest_login_code_scanning(
        self, mock_session_manager: AsyncMock
    ) -> None:
        """
        Verify get_latest_login_code scans peer 777000 and finds code in the first
        valid message even when preceding messages are non-code alerts.
        """
        client = AsyncMock()

        m1 = MagicMock()
        m1.message = "Security alert: new login from Chrome on Windows."  # no code

        m2 = MagicMock()
        m2.message = "Login code: 59381. Do not share."  # valid code

        m3 = MagicMock()
        m3.message = "Older login code: 11111."

        client.get_messages.return_value = [m1, m2, m3]
        mock_session_manager.get_client.return_value = client

        service = ChatService(mock_session_manager)
        code = await service.get_latest_login_code("+15156723850")
        assert code == "59381"

        client.get_messages.assert_awaited_once_with(777000, limit=20)
