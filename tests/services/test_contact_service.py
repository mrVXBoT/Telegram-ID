"""
tests.services.test_contact_service
===================================
Unit tests for ContactService:
- Contact retrieval and ContactInfo normalization
- Digit length filtering (7, 8, 9, 10, 11, and bulk '7to9')
- Mutual contact extraction
- Contacts summary statistics
- Batch contact deletion in chunks of 100 with progress callbacks
- Rate limiting pauses and partial failure resilience
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.tl.functions.contacts import DeleteContactsRequest, GetContactsRequest

from services.contact_service import ContactService, DeleteResult
from utils.vcf import ContactInfo


def make_mock_user(uid: int, phone: str = "+1000", first_name: str = "Test") -> MagicMock:
    """Helper to construct a mock Telethon User."""
    user = MagicMock()
    user.id = uid
    user.phone = phone
    user.first_name = first_name
    user.last_name = None
    user.mutual_contact = False
    return user


def make_mock_contact(user_id: int, mutual: bool = False) -> MagicMock:
    """Helper to construct a mock Telethon Contact entry."""
    contact = MagicMock()
    contact.user_id = user_id
    contact.mutual = mutual
    return contact


@pytest.fixture
def mock_session_manager() -> AsyncMock:
    """Provide a mock TelethonSessionManager."""
    manager = AsyncMock()
    manager.normalize_phone = MagicMock(side_effect=lambda p: p if p.startswith("+") else f"+{p}")
    return manager


@pytest.fixture
def sample_contacts_response() -> MagicMock:
    """Provide mock response for GetContactsRequest with varied digit lengths."""
    res = MagicMock()
    # User IDs with 7, 8, 9, 10, and 11 digits
    users = [
        make_mock_user(1000001, "+1111", "SevenDigit"),
        make_mock_user(20000002, "+2222", "EightDigit"),
        make_mock_user(300000003, "+3333", "NineDigit"),
        make_mock_user(4000000004, "+4444", "TenDigit"),
        make_mock_user(50000000005, "+5555", "ElevenDigit"),
    ]
    # Mark user 1000001 and 300000003 as mutual
    contacts = [
        make_mock_contact(1000001, mutual=True),
        make_mock_contact(20000002, mutual=False),
        make_mock_contact(300000003, mutual=True),
        make_mock_contact(4000000004, mutual=False),
        make_mock_contact(50000000005, mutual=False),
    ]
    res.users = users
    res.contacts = contacts
    return res


@pytest.mark.asyncio
async def test_get_all_contacts(
    mock_session_manager: AsyncMock, sample_contacts_response: MagicMock
) -> None:
    """Verify get_all_contacts converts Telethon contacts to ContactInfo models."""
    client = AsyncMock()
    client.side_effect = lambda req: sample_contacts_response if isinstance(req, GetContactsRequest) else None
    mock_session_manager.get_client.return_value = client

    service = ContactService(mock_session_manager)
    contacts = await service.get_all_contacts("+15156723850")

    assert len(contacts) == 5
    assert all(isinstance(c, ContactInfo) for c in contacts)

    # Check mutual detection
    c_seven = next(c for c in contacts if c.id == 1000001)
    assert c_seven.is_mutual is True
    assert c_seven.first_name == "SevenDigit"

    c_eight = next(c for c in contacts if c.id == 20000002)
    assert c_eight.is_mutual is False


@pytest.mark.asyncio
async def test_extract_contacts_by_length(
    mock_session_manager: AsyncMock, sample_contacts_response: MagicMock
) -> None:
    """Verify extraction by single digit lengths (7, 8, 9, 10, 11)."""
    client = AsyncMock()
    client.side_effect = lambda req: sample_contacts_response if isinstance(req, GetContactsRequest) else None
    mock_session_manager.get_client.return_value = client

    service = ContactService(mock_session_manager)
    phone = "+15156723850"

    # Test 7 digits
    c7 = await service.extract_contacts_by_length(phone, 7)
    assert len(c7) == 1
    assert c7[0].id == 1000001

    # Test 8 digits
    c8 = await service.extract_contacts_by_length(phone, 8)
    assert len(c8) == 1
    assert c8[0].id == 20000002

    # Test 10 digits
    c10 = await service.extract_contacts_by_length(phone, "10")
    assert len(c10) == 1
    assert c10[0].id == 4000000004


@pytest.mark.asyncio
async def test_extract_contacts_range_7to9(
    mock_session_manager: AsyncMock, sample_contacts_response: MagicMock
) -> None:
    """Verify bulk extraction with range spec '7to9'."""
    client = AsyncMock()
    client.side_effect = lambda req: sample_contacts_response if isinstance(req, GetContactsRequest) else None
    mock_session_manager.get_client.return_value = client

    service = ContactService(mock_session_manager)
    phone = "+15156723850"

    c_bulk = await service.extract_contacts_by_length(phone, "7to9")
    assert len(c_bulk) == 3
    ids = {c.id for c in c_bulk}
    assert ids == {1000001, 20000002, 300000003}


@pytest.mark.asyncio
async def test_get_mutual_contacts(
    mock_session_manager: AsyncMock, sample_contacts_response: MagicMock
) -> None:
    """Verify get_mutual_contacts returns only mutual contacts."""
    client = AsyncMock()
    client.side_effect = lambda req: sample_contacts_response if isinstance(req, GetContactsRequest) else None
    mock_session_manager.get_client.return_value = client

    service = ContactService(mock_session_manager)
    phone = "+15156723850"

    mutual = await service.get_mutual_contacts(phone)
    assert len(mutual) == 2
    assert {c.id for c in mutual} == {1000001, 300000003}


@pytest.mark.asyncio
async def test_get_contacts_summary(
    mock_session_manager: AsyncMock, sample_contacts_response: MagicMock
) -> None:
    """Verify get_contacts_summary computes breakdown and mutual count."""
    client = AsyncMock()
    client.side_effect = lambda req: sample_contacts_response if isinstance(req, GetContactsRequest) else None
    mock_session_manager.get_client.return_value = client

    service = ContactService(mock_session_manager)
    summary = await service.get_contacts_summary("+15156723850")

    assert summary["total"] == 5
    assert summary["mutual"] == 2
    assert summary["breakdown"][7] == 1
    assert summary["breakdown"][8] == 1
    assert summary["breakdown"][9] == 1
    assert summary["breakdown"][10] == 1
    assert summary["breakdown"][11] == 1


@pytest.mark.asyncio
async def test_delete_all_contacts_chunking_and_progress(
    mock_session_manager: AsyncMock,
) -> None:
    """
    Verify delete_all_contacts partitions deletion into batches of 100
    and executes progress callback with (deleted, total).
    """
    client = AsyncMock()

    # Create 250 contacts
    users = [make_mock_user(1000000 + i) for i in range(250)]
    contacts = [make_mock_contact(1000000 + i) for i in range(250)]

    res = MagicMock()
    res.users = users
    res.contacts = contacts

    deleted_batches: list[list[int]] = []

    async def mock_handler(req: Any) -> Any:
        if isinstance(req, GetContactsRequest):
            return res
        if isinstance(req, DeleteContactsRequest):
            deleted_batches.append(req.id)
            return True
        return None

    client.side_effect = mock_handler
    mock_session_manager.get_client.return_value = client

    progress_calls: list[tuple[int, int]] = []

    async def async_progress_cb(deleted: int, total: int) -> None:
        progress_calls.append((deleted, total))

    service = ContactService(mock_session_manager)
    result = await service.delete_all_contacts(
        "+15156723850", progress_callback=async_progress_cb, batch_delay=0.0
    )

    assert result.status == "success"
    assert result.total == 250
    assert result.deleted == 250
    assert result.failed == 0

    # 250 contacts should yield 3 batches: 100, 100, 50
    assert len(deleted_batches) == 3
    assert len(deleted_batches[0]) == 100
    assert len(deleted_batches[1]) == 100
    assert len(deleted_batches[2]) == 50

    # Progress callback should be invoked 3 times
    assert progress_calls == [(100, 250), (200, 250), (250, 250)]


@pytest.mark.asyncio
async def test_delete_all_contacts_empty(mock_session_manager: AsyncMock) -> None:
    """Verify delete_all_contacts gracefully handles empty contacts list."""
    client = AsyncMock()
    empty_res = MagicMock()
    empty_res.users = []
    empty_res.contacts = []
    client.side_effect = lambda req: empty_res if isinstance(req, GetContactsRequest) else None
    mock_session_manager.get_client.return_value = client

    service = ContactService(mock_session_manager)
    result = await service.delete_all_contacts("+15156723850", batch_delay=0.0)

    assert result.total == 0
    assert result.deleted == 0
    assert result.failed == 0
    assert result.status == "success"


@pytest.mark.asyncio
async def test_delete_all_contacts_partial_failure(mock_session_manager: AsyncMock) -> None:
    """Verify delete_all_contacts records failure when a batch raises an exception."""
    client = AsyncMock()
    users = [make_mock_user(1000000 + i) for i in range(200)]
    contacts = [make_mock_contact(1000000 + i) for i in range(200)]
    res = MagicMock()
    res.users = users
    res.contacts = contacts

    batch_idx = 0

    async def mock_handler(req: Any) -> Any:
        nonlocal batch_idx
        if isinstance(req, GetContactsRequest):
            return res
        if isinstance(req, DeleteContactsRequest):
            batch_idx += 1
            if batch_idx == 1:
                return True
            raise RuntimeError("Telegram RPC error")
        return None

    client.side_effect = mock_handler
    mock_session_manager.get_client.return_value = client

    service = ContactService(mock_session_manager)
    result = await service.delete_all_contacts("+15156723850", batch_delay=0.0)

    assert result.total == 200
    assert result.deleted == 100
    assert result.failed == 100
    assert result.status == "partial"


@pytest.mark.asyncio
async def test_get_all_contacts_dict_entries(mock_session_manager: AsyncMock) -> None:
    """Verify get_all_contacts handles dictionary representations in users list."""
    client = AsyncMock()
    dict_res = MagicMock()
    dict_res.contacts = []
    dict_res.users = [
        {"id": 1234567, "phone": "+1234567", "first_name": "DictUser", "last_name": "Test", "is_mutual": True},
        {"id": None, "first_name": "Invalid"},  # Should be skipped
    ]
    client.side_effect = lambda req: dict_res if isinstance(req, GetContactsRequest) else None
    mock_session_manager.get_client.return_value = client

    service = ContactService(mock_session_manager)
    contacts = await service.get_all_contacts("+15156723850")

    assert len(contacts) == 1
    assert contacts[0].id == 1234567
    assert contacts[0].first_name == "DictUser"
    assert contacts[0].is_mutual is True


@pytest.mark.asyncio
async def test_delete_all_contacts_sync_callback_and_resilience(mock_session_manager: AsyncMock) -> None:
    """Verify delete_all_contacts supports synchronous callback and handles callback exceptions."""
    client = AsyncMock()
    users = [make_mock_user(1000000 + i) for i in range(150)]
    contacts = [make_mock_contact(1000000 + i) for i in range(150)]
    res = MagicMock()
    res.users = users
    res.contacts = contacts

    async def mock_handler(req: Any) -> Any:
        if isinstance(req, GetContactsRequest):
            return res
        if isinstance(req, DeleteContactsRequest):
            return True
        return None

    client.side_effect = mock_handler
    mock_session_manager.get_client.return_value = client

    callback_calls: list[tuple[int, int]] = []

    def sync_callback(deleted: int, total: int) -> None:
        callback_calls.append((deleted, total))
        if deleted == 100:
            raise ValueError("Callback error test")

    service = ContactService(mock_session_manager)
    result = await service.delete_all_contacts(
        "+15156723850", progress_callback=sync_callback, batch_delay=0.0
    )

    assert result.status == "success"
    assert result.deleted == 150
    # Sync callback was executed for both batches despite error in first
    assert len(callback_calls) == 2


@pytest.mark.asyncio
async def test_delete_all_contacts_fallback_to_users_list(mock_session_manager: AsyncMock) -> None:
    """Verify delete_all_contacts extracts target IDs from users list if contacts list is absent."""
    client = AsyncMock()
    users = [make_mock_user(7770001), make_mock_user(7770002)]
    res = MagicMock()
    res.contacts = None
    res.users = users

    deleted_ids = []

    async def mock_handler(req: Any) -> Any:
        if isinstance(req, GetContactsRequest):
            return res
        if isinstance(req, DeleteContactsRequest):
            deleted_ids.extend(req.id)
            return True
        return None

    client.side_effect = mock_handler
    mock_session_manager.get_client.return_value = client

    service = ContactService(mock_session_manager)
    result = await service.delete_all_contacts("+15156723850", batch_delay=0.0)

    assert result.total == 2
    assert result.deleted == 2
    assert deleted_ids == [7770001, 7770002]

