"""
tests.services.test_session_manager
===================================
Unit tests for TelethonSessionManager:
- Connection pooling and client caching
- Per-phone asyncio.Lock synchronization
- Lazy client connection on active loop
- Safe disconnect and session file cleanup (Windows WinError 32 prevention)
- Disconnect all and context manager lifecycle
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.session_manager import TelethonSessionManager


@pytest.fixture
def temp_sessions_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for session files."""
    sdir = tmp_path / "sessions"
    sdir.mkdir(parents=True, exist_ok=True)
    return sdir


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create a mock Telethon TelegramClient."""
    client = AsyncMock()
    client.is_connected = MagicMock(return_value=True)
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=True)
    client.session = MagicMock()
    client.session.close = MagicMock()
    return client


def test_normalize_phone(temp_sessions_dir: Path) -> None:
    """Verify phone normalization removes formatting and enforces '+'."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    assert manager.normalize_phone("+1 (515) 672-3850") == "+15156723850"
    assert manager.normalize_phone("15156723850") == "+15156723850"
    assert manager.normalize_phone("+98 912 345 6789") == "+989123456789"


def test_session_paths(temp_sessions_dir: Path) -> None:
    """Verify base session path and .session file path generation."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    base_path = manager.get_session_base_path("+15156723850")
    file_path = manager.get_session_file_path("+15156723850")

    assert base_path == temp_sessions_dir / "+15156723850"
    assert file_path == temp_sessions_dir / "+15156723850.session"


def test_session_exists(temp_sessions_dir: Path) -> None:
    """Verify session_exists correctly checks for .session file existence."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"
    assert not manager.session_exists(phone)

    # Create dummy session file
    session_file = manager.get_session_file_path(phone)
    session_file.write_bytes(b"dummy session content")

    assert manager.session_exists(phone)


@pytest.mark.asyncio
async def test_get_client_pooling(temp_sessions_dir: Path, mock_client: AsyncMock) -> None:
    """Verify get_client caches and reuses the same client instance."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"

    with patch("services.session_manager.TelegramClient", return_value=mock_client) as mock_cls:
        client1 = await manager.get_client(phone)
        client2 = await manager.get_client(phone)

        assert client1 is client2
        assert client1 is mock_client
        # Constructor should only be called once due to pooling
        mock_cls.assert_called_once_with(
            str(temp_sessions_dir / "+15156723850"), 12345, "test_hash"
        )
        assert manager.has_client(phone)
        assert manager.get_active_phones() == [phone]


@pytest.mark.asyncio
async def test_get_client_reconnects_when_disconnected(
    temp_sessions_dir: Path, mock_client: AsyncMock
) -> None:
    """Verify existing pooled client reconnects if currently disconnected."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"

    with patch("services.session_manager.TelegramClient", return_value=mock_client):
        # Initial connection
        await manager.get_client(phone)
        assert mock_client.connect.call_count == 1

        # Simulate disconnect
        mock_client.is_connected.return_value = False

        # Request client again
        await manager.get_client(phone, connect=True)
        assert mock_client.connect.call_count == 2


@pytest.mark.asyncio
async def test_per_phone_lock_synchronization(temp_sessions_dir: Path) -> None:
    """Verify distinct locks for different phones, same lock for same phone."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone1 = "+15156723850"
    phone2 = "+14417071240"

    lock1 = manager.get_lock(phone1)
    lock1_again = manager.get_lock(phone1)
    lock2 = manager.get_lock(phone2)

    assert lock1 is lock1_again
    assert lock1 is not lock2


@pytest.mark.asyncio
async def test_is_authorized(temp_sessions_dir: Path, mock_client: AsyncMock) -> None:
    """Verify is_authorized returns client authorization status."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"

    with patch("services.session_manager.TelegramClient", return_value=mock_client):
        mock_client.is_user_authorized.return_value = True
        assert await manager.is_authorized(phone) is True

        mock_client.is_user_authorized.return_value = False
        assert await manager.is_authorized(phone) is False


@pytest.mark.asyncio
async def test_disconnect_safe_cleanup(temp_sessions_dir: Path, mock_client: AsyncMock) -> None:
    """Verify disconnect closes client connection and SQLite session handle."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"

    with patch("services.session_manager.TelegramClient", return_value=mock_client):
        await manager.get_client(phone)
        assert manager.has_client(phone)

        await manager.disconnect(phone)

        mock_client.disconnect.assert_awaited_once()
        mock_client.session.close.assert_called_once()
        assert not manager.has_client(phone)
        assert manager.get_active_phones() == []


@pytest.mark.asyncio
async def test_disconnect_all(temp_sessions_dir: Path) -> None:
    """Verify disconnect_all cleanly terminates all pooled clients."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone1 = "+15156723850"
    phone2 = "+14417071240"

    client1 = AsyncMock()
    client1.is_connected = MagicMock(return_value=True)
    client2 = AsyncMock()
    client2.is_connected = MagicMock(return_value=True)

    with patch("services.session_manager.TelegramClient", side_effect=[client1, client2]):
        await manager.get_client(phone1)
        await manager.get_client(phone2)
        assert len(manager.get_active_phones()) == 2

        await manager.disconnect_all()

        client1.disconnect.assert_awaited_once()
        client2.disconnect.assert_awaited_once()
        assert len(manager.get_active_phones()) == 0


@pytest.mark.asyncio
async def test_remove_session_file_safe_ordering(
    temp_sessions_dir: Path, mock_client: AsyncMock
) -> None:
    """
    Verify disconnect precedes file removal to prevent Windows WinError 32.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"
    session_file = manager.get_session_file_path(phone)
    session_file.write_bytes(b"dummy session bytes")

    call_order: list[str] = []

    async def fake_disconnect() -> None:
        call_order.append("disconnect")

    mock_client.disconnect = AsyncMock(side_effect=fake_disconnect)

    with patch("services.session_manager.TelegramClient", return_value=mock_client):
        await manager.get_client(phone)

        # Intercept unlink to verify ordering
        original_unlink = Path.unlink

        def tracked_unlink(p: Path, *args, **kwargs):
            if p == session_file:
                call_order.append("unlink")
            return original_unlink(p, *args, **kwargs)

        with patch.object(Path, "unlink", side_effect=tracked_unlink, autospec=True):
            removed = await manager.remove_session_file(phone)

        assert removed is True
        assert call_order == ["disconnect", "unlink"]
        assert not session_file.exists()


@pytest.mark.asyncio
async def test_remove_nonexistent_session_file(temp_sessions_dir: Path) -> None:
    """Verify remove_session_file returns False when file is absent."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+999999999999"
    assert not manager.session_exists(phone)

    removed = await manager.remove_session_file(phone)
    assert removed is False


@pytest.mark.asyncio
async def test_async_context_manager(temp_sessions_dir: Path, mock_client: AsyncMock) -> None:
    """Verify async context manager calls disconnect_all on exit."""
    phone = "+15156723850"

    with patch("services.session_manager.TelegramClient", return_value=mock_client):
        async with TelethonSessionManager(
            api_id=12345,
            api_hash="test_hash",
            sessions_dir=temp_sessions_dir,
        ) as manager:
            await manager.get_client(phone)
            assert manager.has_client(phone)

        mock_client.disconnect.assert_awaited_once()
        assert not manager.has_client(phone)


@pytest.mark.asyncio
async def test_get_client_connect_false(temp_sessions_dir: Path, mock_client: AsyncMock) -> None:
    """Verify get_client with connect=False does not call client.connect()."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"

    with patch("services.session_manager.TelegramClient", return_value=mock_client):
        client = await manager.get_client(phone, connect=False)
        assert client is mock_client
        mock_client.connect.assert_not_called()


@pytest.mark.asyncio
async def test_disconnect_exception_resilience(
    temp_sessions_dir: Path, mock_client: AsyncMock
) -> None:
    """Verify disconnect safely cleans up even if client.disconnect raises an error."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"
    mock_client.disconnect.side_effect = RuntimeError("Socket already closed")

    with patch("services.session_manager.TelegramClient", return_value=mock_client):
        await manager.get_client(phone)
        assert manager.has_client(phone)

        # Disconnect should catch exception and still remove from _clients
        await manager.disconnect(phone)
        assert not manager.has_client(phone)


@pytest.mark.asyncio
async def test_disconnect_all_exception_resilience(temp_sessions_dir: Path) -> None:
    """Verify disconnect_all continues disconnecting other clients if one raises."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    client1 = AsyncMock()
    client1.is_connected = MagicMock(return_value=True)
    client1.disconnect.side_effect = RuntimeError("Failed client 1")

    client2 = AsyncMock()
    client2.is_connected = MagicMock(return_value=True)

    with patch("services.session_manager.TelegramClient", side_effect=[client1, client2]):
        await manager.get_client("+1111111111")
        await manager.get_client("+2222222222")

        await manager.disconnect_all()
        client2.disconnect.assert_awaited_once()
        assert len(manager.get_active_phones()) == 0


@pytest.mark.asyncio
async def test_remove_session_file_permission_error_reraised(
    temp_sessions_dir: Path, mock_client: AsyncMock
) -> None:
    """Verify PermissionError during file unlinking is re-raised."""
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"
    session_file = manager.get_session_file_path(phone)
    session_file.write_bytes(b"content")

    with patch("services.session_manager.TelegramClient", return_value=mock_client):
        await manager.get_client(phone)

        with patch.object(Path, "unlink", side_effect=PermissionError("File locked by process")):
            with pytest.raises(PermissionError):
                await manager.remove_session_file(phone)

