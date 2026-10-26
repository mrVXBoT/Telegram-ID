"""
tests.services.test_auth_service
================================
Unit tests for AuthService:
- Verification code dispatch (send_code)
- Telethon exception mapping (PhoneNumberInvalid, PhoneNumberBanned, FloodWait)
- Sign-in with verification code
- 2FA challenge detection (SessionPasswordNeededError -> 2fa_required)
- 2FA password verification (sign_in_2fa)
- Error mapping (invalid code, expired code, flood wait, invalid password)
- Account logout and session teardown
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from services.auth_service import (
    AuthService,
    FloodWaitAuthError,
    PhoneNumberBanned,
    PhoneNumberInvalid,
    SignInResult,
)


@pytest.fixture
def mock_session_manager() -> AsyncMock:
    """Provide a mock TelethonSessionManager."""
    manager = AsyncMock()
    manager.normalize_phone = MagicMock(side_effect=lambda p: p if p.startswith("+") else f"+{p}")
    manager.remove_session_file = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def mock_client() -> AsyncMock:
    """Provide a mock TelegramClient."""
    client = AsyncMock()
    client.is_connected = MagicMock(return_value=True)
    client.is_user_authorized = AsyncMock(return_value=False)
    client.send_code_request = AsyncMock()
    client.sign_in = AsyncMock()
    client.log_out = AsyncMock()

    # Default mock user
    me = MagicMock()
    me.id = 123456789
    me.first_name = "Alice"
    me.last_name = "Smith"
    me.username = "alicesmith"
    client.get_me = AsyncMock(return_value=me)

    return client


@pytest.mark.asyncio
async def test_send_code_success(mock_session_manager: AsyncMock, mock_client: AsyncMock) -> None:
    """Verify send_code returns phone_code_hash and caches it."""
    mock_session_manager.get_client.return_value = mock_client
    sent_code = MagicMock()
    sent_code.phone_code_hash = "hash_xyz_123"
    mock_client.send_code_request.return_value = sent_code

    service = AuthService(mock_session_manager)
    phone = "+15156723850"

    hash_val = await service.send_code(phone)

    assert hash_val == "hash_xyz_123"
    assert service.get_cached_hash(phone) == "hash_xyz_123"
    mock_client.send_code_request.assert_awaited_once_with("+15156723850")


@pytest.mark.asyncio
async def test_send_code_phone_number_invalid(
    mock_session_manager: AsyncMock, mock_client: AsyncMock
) -> None:
    """Verify send_code maps PhoneNumberInvalidError to PhoneNumberInvalid."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.send_code_request.side_effect = PhoneNumberInvalidError(request=None)

    service = AuthService(mock_session_manager)
    phone = "+10000000000"

    with pytest.raises(PhoneNumberInvalid) as exc_info:
        await service.send_code(phone)
    assert "invalid" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_send_code_phone_number_banned(
    mock_session_manager: AsyncMock, mock_client: AsyncMock
) -> None:
    """Verify send_code maps PhoneNumberBannedError to PhoneNumberBanned."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.send_code_request.side_effect = PhoneNumberBannedError(request=None)

    service = AuthService(mock_session_manager)
    phone = "+15156723850"

    with pytest.raises(PhoneNumberBanned) as exc_info:
        await service.send_code(phone)
    assert "banned" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_send_code_flood_wait(
    mock_session_manager: AsyncMock, mock_client: AsyncMock
) -> None:
    """Verify send_code maps FloodWaitError to FloodWaitAuthError with seconds."""
    mock_session_manager.get_client.return_value = mock_client
    flood_error = FloodWaitError(request=None)
    flood_error.seconds = 75
    mock_client.send_code_request.side_effect = flood_error

    service = AuthService(mock_session_manager)
    phone = "+15156723850"

    with pytest.raises(FloodWaitAuthError) as exc_info:
        await service.send_code(phone)
    assert exc_info.value.seconds == 75
    assert "75" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sign_in_success(mock_session_manager: AsyncMock, mock_client: AsyncMock) -> None:
    """Verify standard code sign_in returns success SignInResult."""
    mock_session_manager.get_client.return_value = mock_client
    service = AuthService(mock_session_manager)
    phone = "+15156723850"
    service.set_cached_hash(phone, "cached_hash")

    result = await service.sign_in(phone=phone, code="12345")

    assert result.is_success is True
    assert result.status == "success"
    assert result.user_id == 123456789
    assert result.first_name == "Alice"
    assert result.last_name == "Smith"
    assert result.username == "alicesmith"
    # Cached hash should be cleared on success
    assert service.get_cached_hash(phone) is None
    mock_client.sign_in.assert_awaited_once_with(
        phone="+15156723850",
        code="12345",
        phone_code_hash="cached_hash",
    )


@pytest.mark.asyncio
async def test_sign_in_requires_2fa(
    mock_session_manager: AsyncMock, mock_client: AsyncMock
) -> None:
    """Verify sign_in detects SessionPasswordNeededError and returns 2fa_required."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.sign_in.side_effect = SessionPasswordNeededError(request=None)

    service = AuthService(mock_session_manager)
    phone = "+15156723850"

    result = await service.sign_in(phone=phone, code="12345", phone_code_hash="hash")

    assert result.status == "2fa_required"
    assert result.requires_2fa is True
    assert result.is_success is False


@pytest.mark.asyncio
async def test_sign_in_2fa_success(
    mock_session_manager: AsyncMock, mock_client: AsyncMock
) -> None:
    """Verify 2FA password verification completes sign-in successfully."""
    mock_session_manager.get_client.return_value = mock_client

    service = AuthService(mock_session_manager)
    phone = "+15156723850"

    result = await service.sign_in_2fa(phone=phone, password="secret_password")

    assert result.status == "success"
    assert result.is_success is True
    assert result.user_id == 123456789
    mock_client.sign_in.assert_awaited_once_with(password="secret_password")


@pytest.mark.asyncio
async def test_sign_in_invalid_code(
    mock_session_manager: AsyncMock, mock_client: AsyncMock
) -> None:
    """Verify sign_in handles PhoneCodeInvalidError."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.sign_in.side_effect = PhoneCodeInvalidError(request=None)

    service = AuthService(mock_session_manager)
    result = await service.sign_in(phone="+15156723850", code="00000")

    assert result.status == "invalid_code"
    assert result.is_success is False


@pytest.mark.asyncio
async def test_sign_in_expired_code(
    mock_session_manager: AsyncMock, mock_client: AsyncMock
) -> None:
    """Verify sign_in handles PhoneCodeExpiredError."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.sign_in.side_effect = PhoneCodeExpiredError(request=None)

    service = AuthService(mock_session_manager)
    result = await service.sign_in(phone="+15156723850", code="12345")

    assert result.status == "expired_code"
    assert result.is_success is False


@pytest.mark.asyncio
async def test_sign_in_banned_phone(
    mock_session_manager: AsyncMock, mock_client: AsyncMock
) -> None:
    """Verify sign_in handles PhoneNumberBannedError."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.sign_in.side_effect = PhoneNumberBannedError(request=None)

    service = AuthService(mock_session_manager)
    result = await service.sign_in(phone="+15156723850", code="12345")

    assert result.status == "banned"
    assert result.is_success is False


@pytest.mark.asyncio
async def test_sign_in_flood_wait(
    mock_session_manager: AsyncMock, mock_client: AsyncMock
) -> None:
    """Verify sign_in handles FloodWaitError with wait_seconds."""
    mock_session_manager.get_client.return_value = mock_client
    err = FloodWaitError(request=None)
    err.seconds = 180
    mock_client.sign_in.side_effect = err

    service = AuthService(mock_session_manager)
    result = await service.sign_in(phone="+15156723850", code="12345")

    assert result.status == "flood_wait"
    assert result.wait_seconds == 180
    assert result.is_success is False


@pytest.mark.asyncio
async def test_sign_in_invalid_2fa_password(
    mock_session_manager: AsyncMock, mock_client: AsyncMock
) -> None:
    """Verify sign_in handles PasswordHashInvalidError."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.sign_in.side_effect = PasswordHashInvalidError(request=None)

    service = AuthService(mock_session_manager)
    result = await service.sign_in_2fa(phone="+15156723850", password="wrong_password")

    assert result.status == "invalid_password"
    assert result.is_success is False


@pytest.mark.asyncio
async def test_sign_in_generic_error(
    mock_session_manager: AsyncMock, mock_client: AsyncMock
) -> None:
    """Verify sign_in gracefully handles unexpected exceptions."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.sign_in.side_effect = RuntimeError("Network connection reset")

    service = AuthService(mock_session_manager)
    result = await service.sign_in(phone="+15156723850", code="12345")

    assert result.status == "error"
    assert "Network connection reset" in (result.message or "")


@pytest.mark.asyncio
async def test_log_out(mock_session_manager: AsyncMock, mock_client: AsyncMock) -> None:
    """Verify log_out logs out authorized client and removes session file."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.is_user_authorized.return_value = True

    service = AuthService(mock_session_manager)
    phone = "+15156723850"
    service.set_cached_hash(phone, "cached_hash")

    success = await service.log_out(phone)

    assert success is True
    mock_client.log_out.assert_awaited_once()
    mock_session_manager.remove_session_file.assert_awaited_once_with("+15156723850")
    assert service.get_cached_hash(phone) is None


@pytest.mark.asyncio
async def test_send_code_dict_response(mock_session_manager: AsyncMock, mock_client: AsyncMock) -> None:
    """Verify send_code accepts dict response containing phone_code_hash."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.send_code_request.return_value = {"phone_code_hash": "dict_hash_999"}

    service = AuthService(mock_session_manager)
    h = await service.send_code("+15156723850")
    assert h == "dict_hash_999"


@pytest.mark.asyncio
async def test_send_code_missing_hash_raises(mock_session_manager: AsyncMock, mock_client: AsyncMock) -> None:
    """Verify send_code raises AuthServiceError when no hash is present in response."""
    from services.auth_service import AuthServiceError

    mock_session_manager.get_client.return_value = mock_client
    mock_client.send_code_request.return_value = object()

    service = AuthService(mock_session_manager)
    with pytest.raises(AuthServiceError):
        await service.send_code("+15156723850")


@pytest.mark.asyncio
async def test_sign_in_code_formatting_cleaned(mock_session_manager: AsyncMock, mock_client: AsyncMock) -> None:
    """Verify sign_in cleans spaces and hyphens from verification code."""
    mock_session_manager.get_client.return_value = mock_client
    service = AuthService(mock_session_manager)

    await service.sign_in(phone="+15156723850", code=" 1 2 - 3 4 5 ", phone_code_hash="hash")
    mock_client.sign_in.assert_awaited_once_with(
        phone="+15156723850",
        code="12345",
        phone_code_hash="hash",
    )


@pytest.mark.asyncio
async def test_log_out_unauthorized_client(mock_session_manager: AsyncMock, mock_client: AsyncMock) -> None:
    """Verify log_out does not call client.log_out if user is not authorized."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.is_user_authorized.return_value = False

    service = AuthService(mock_session_manager)
    success = await service.log_out("+15156723850")

    assert success is True
    mock_client.log_out.assert_not_called()
    mock_session_manager.remove_session_file.assert_awaited_once_with("+15156723850")


@pytest.mark.asyncio
async def test_log_out_exception_resilience(mock_session_manager: AsyncMock, mock_client: AsyncMock) -> None:
    """Verify log_out proceeds to remove session file even if client.log_out() raises an error."""
    mock_session_manager.get_client.return_value = mock_client
    mock_client.is_user_authorized.return_value = True
    mock_client.log_out.side_effect = RuntimeError("RPC logout failure")

    service = AuthService(mock_session_manager)
    success = await service.log_out("+15156723850")

    assert success is True
    mock_session_manager.remove_session_file.assert_awaited_once_with("+15156723850")

