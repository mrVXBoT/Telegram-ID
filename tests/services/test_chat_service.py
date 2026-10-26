"""
tests.services.test_chat_service
================================
Unit tests for ChatService:
- Creator chat inspection and type classification (channel, supergroup, group)
- Creator ownership filtering (creator=True only)
- Supergroup migration deduplication (migrated_from_chat_id)
- History visibility detection (hidden_prehistory)
- Public link, invite link, and fallback link resolution
- Telegram official auth code extraction from peer 777000 (\\b\\d{5}\\b)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest, GetDialogsRequest
from telethon.tl.types import Channel, Chat

from services.chat_service import ChatInfo, ChatService


@pytest.fixture
def mock_session_manager() -> AsyncMock:
    """Provide a mock TelethonSessionManager."""
    manager = AsyncMock()
    manager.normalize_phone = MagicMock(side_effect=lambda p: p if p.startswith("+") else f"+{p}")
    return manager


@pytest.mark.asyncio
async def test_list_creator_chats_classification_and_ownership(
    mock_session_manager: AsyncMock,
) -> None:
    """Verify only creator chats are returned, classified into channel, supergroup, group."""
    client = AsyncMock()

    # Create chats
    ch1 = MagicMock(spec=Channel)
    ch1.id = 101
    ch1.title = "News Channel"
    ch1.creator = True
    ch1.megagroup = False
    ch1.username = "newschannel"

    sg1 = MagicMock(spec=Channel)
    sg1.id = 102
    sg1.title = "Community Supergroup"
    sg1.creator = True
    sg1.megagroup = True
    sg1.username = None

    gr1 = MagicMock(spec=Chat)
    gr1.id = 103
    gr1.title = "Small Team Chat"
    gr1.creator = True

    non_creator = MagicMock(spec=Channel)
    non_creator.id = 999
    non_creator.title = "Other Channel"
    non_creator.creator = False
    non_creator.megagroup = False

    dialogs = MagicMock()
    dialogs.chats = [ch1, sg1, gr1, non_creator]

    # Mock GetFullChannelRequest
    full_resp = MagicMock()
    full_resp.full_chat.migrated_from_chat_id = None
    full_resp.full_chat.hidden_prehistory = False

    # Mock ExportChatInviteRequest
    invite_resp = MagicMock()
    invite_resp.link = "https://t.me/+invite123"

    async def mock_handler(req):
        if isinstance(req, GetDialogsRequest):
            return dialogs
        if isinstance(req, GetFullChannelRequest):
            return full_resp
        if isinstance(req, ExportChatInviteRequest):
            return invite_resp
        return None

    client.side_effect = mock_handler
    client.get_messages = AsyncMock(return_value=[])
    mock_session_manager.get_client.return_value = client

    service = ChatService(mock_session_manager)
    results = await service.list_creator_chats("+15156723850")

    # Non-creator chat (999) must be excluded
    assert len(results) == 3
    ids = [c.id for c in results]
    assert 999 not in ids

    # Check classifications
    c_map = {c.id: c for c in results}
    assert c_map[101].is_channel is True
    assert c_map[101].type == "channel"
    assert c_map[101].link == "https://t.me/newschannel"

    assert c_map[102].is_supergroup is True
    assert c_map[102].type == "supergroup"
    assert c_map[102].link == "https://t.me/+invite123"

    assert c_map[103].is_group is True
    assert c_map[103].type == "group"


@pytest.mark.asyncio
async def test_list_creator_chats_migrated_supergroup_deduplication(
    mock_session_manager: AsyncMock,
) -> None:
    """
    Verify basic Chat is dropped if its ID matches migrated_from_chat_id
    of an existing supergroup.
    """
    client = AsyncMock()

    # Legacy basic chat
    basic_chat = MagicMock(spec=Chat)
    basic_chat.id = 555
    basic_chat.title = "Old Basic Group"
    basic_chat.creator = True

    # New supergroup it migrated into
    supergroup = MagicMock(spec=Channel)
    supergroup.id = 777
    supergroup.title = "Migrated Supergroup"
    supergroup.creator = True
    supergroup.megagroup = True
    supergroup.username = "migratedgroup"

    dialogs = MagicMock()
    dialogs.chats = [basic_chat, supergroup]

    full_sg = MagicMock()
    full_sg.full_chat.migrated_from_chat_id = 555  # Points to basic_chat.id
    full_sg.full_chat.hidden_prehistory = True

    async def mock_handler(req):
        if isinstance(req, GetDialogsRequest):
            return dialogs
        if isinstance(req, GetFullChannelRequest):
            return full_sg
        return None

    client.side_effect = mock_handler
    client.get_messages = AsyncMock(return_value=[])
    mock_session_manager.get_client.return_value = client

    service = ChatService(mock_session_manager)
    results = await service.list_creator_chats("+15156723850")

    # Basic chat 555 must be omitted because it migrated to supergroup 777
    assert len(results) == 1
    assert results[0].id == 777
    assert results[0].migrated_from_chat_id == 555
    assert results[0].hidden_prehistory is True
    assert results[0].history_visibility == "Hidden"


@pytest.mark.asyncio
async def test_list_creator_chats_creation_date_resolution(
    mock_session_manager: AsyncMock,
) -> None:
    """Verify earliest message date is resolved and formatted as YYYY-MM-DD."""
    client = AsyncMock()

    ch = MagicMock(spec=Channel)
    ch.id = 1234
    ch.title = "Dated Channel"
    ch.creator = True
    ch.megagroup = False
    ch.username = "dated"

    dialogs = MagicMock()
    dialogs.chats = [ch]

    client.side_effect = lambda req: dialogs if isinstance(req, GetDialogsRequest) else None

    # Earliest message mock
    earliest_msg = MagicMock()
    earliest_msg.date = datetime(2023, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
    client.get_messages = AsyncMock(return_value=[earliest_msg])

    mock_session_manager.get_client.return_value = client

    service = ChatService(mock_session_manager)
    results = await service.list_creator_chats("+15156723850")

    assert len(results) == 1
    assert results[0].creation_date == "2023-07-15"
    assert results[0].creation_year == 2023


@pytest.mark.asyncio
async def test_get_latest_login_code_success(mock_session_manager: AsyncMock) -> None:
    """Verify 5-digit verification code is extracted from peer 777000."""
    client = AsyncMock()

    msg1 = MagicMock()
    msg1.message = "Login code: 49201. Do not give this code to anyone."

    msg2 = MagicMock()
    msg2.message = "Your Telegram account was logged in from a new device."

    client.get_messages = AsyncMock(return_value=[msg1, msg2])
    mock_session_manager.get_client.return_value = client

    service = ChatService(mock_session_manager)
    phone = "+15156723850"

    code = await service.get_latest_login_code(phone)
    assert code == "49201"

    full_msg = await service.get_latest_login_message(phone)
    assert full_msg == "Login code: 49201. Do not give this code to anyone."
    client.get_messages.assert_awaited_with(777000, limit=20)


@pytest.mark.asyncio
async def test_get_latest_login_code_none_when_absent(
    mock_session_manager: AsyncMock,
) -> None:
    """Verify None is returned when messages do not contain a 5-digit code."""
    client = AsyncMock()

    msg1 = MagicMock()
    msg1.message = "Welcome to Telegram Desktop!"

    client.get_messages = AsyncMock(return_value=[msg1])
    mock_session_manager.get_client.return_value = client

    service = ChatService(mock_session_manager)
    code = await service.get_latest_login_code("+15156723850")
    assert code is None


@pytest.mark.asyncio
async def test_get_latest_login_code_empty_messages(
    mock_session_manager: AsyncMock,
) -> None:
    """Verify None is returned when peer 777000 has no messages."""
    client = AsyncMock()
    client.get_messages = AsyncMock(return_value=[])
    mock_session_manager.get_client.return_value = client

    service = ChatService(mock_session_manager)
    code = await service.get_latest_login_code("+15156723850")
    assert code is None


@pytest.mark.asyncio
async def test_list_creator_chats_fallback_link_on_export_error(mock_session_manager: AsyncMock) -> None:
    """Verify link resolution falls back to https://t.me/c/{id} if ExportChatInviteRequest fails."""
    client = AsyncMock()

    ch = MagicMock(spec=Channel)
    ch.id = -1001987654321
    ch.title = "Private Channel"
    ch.creator = True
    ch.megagroup = False
    ch.username = None

    dialogs = MagicMock()
    dialogs.chats = [ch]

    async def mock_handler(req):
        if isinstance(req, GetDialogsRequest):
            return dialogs
        if isinstance(req, ExportChatInviteRequest):
            raise RuntimeError("Cannot export invite link")
        return None

    client.side_effect = mock_handler
    client.get_messages = AsyncMock(return_value=[])
    mock_session_manager.get_client.return_value = client

    service = ChatService(mock_session_manager)
    results = await service.list_creator_chats("+15156723850")

    assert len(results) == 1
    # -100 stripped gives 1987654321
    assert results[0].link == "https://t.me/c/1987654321"


@pytest.mark.asyncio
async def test_list_creator_chats_hidden_prehistory_via_available_min_id(mock_session_manager: AsyncMock) -> None:
    """Verify hidden_prehistory fallback logic using available_min_id > 1."""
    client = AsyncMock()

    sg = MagicMock(spec=Channel)
    sg.id = 8888
    sg.title = "MinId Supergroup"
    sg.creator = True
    sg.megagroup = True
    sg.username = "minid"

    dialogs = MagicMock()
    dialogs.chats = [sg]

    full_resp = MagicMock()
    full_resp.full_chat.migrated_from_chat_id = None
    full_resp.full_chat.hidden_prehistory = None  # None triggers fallback
    full_resp.full_chat.available_min_id = 50     # > 1 means history is hidden

    async def mock_handler(req):
        if isinstance(req, GetDialogsRequest):
            return dialogs
        if isinstance(req, GetFullChannelRequest):
            return full_resp
        return None

    client.side_effect = mock_handler
    client.get_messages = AsyncMock(return_value=[])
    mock_session_manager.get_client.return_value = client

    service = ChatService(mock_session_manager)
    results = await service.list_creator_chats("+15156723850")

    assert len(results) == 1
    assert results[0].hidden_prehistory is True
    assert results[0].history_visibility == "Hidden"


@pytest.mark.asyncio
async def test_get_latest_login_code_msg_text_field(mock_session_manager: AsyncMock) -> None:
    """Verify get_latest_login_code supports msg.text in addition to msg.message."""
    client = AsyncMock()

    msg = MagicMock()
    msg.message = None
    msg.text = "Your verification code is: 83921. Valid for 10 minutes."

    client.get_messages = AsyncMock(return_value=[msg])
    mock_session_manager.get_client.return_value = client

    service = ChatService(mock_session_manager)
    code = await service.get_latest_login_code("+15156723850")
    assert code == "83921"


@pytest.mark.asyncio
async def test_get_latest_login_code_exception_graceful(mock_session_manager: AsyncMock) -> None:
    """Verify get_latest_login_code catches exceptions and returns None gracefully."""
    client = AsyncMock()
    client.get_messages.side_effect = RuntimeError("Telegram connection error")
    mock_session_manager.get_client.return_value = client

    service = ChatService(mock_session_manager)
    code = await service.get_latest_login_code("+15156723850")
    assert code is None

