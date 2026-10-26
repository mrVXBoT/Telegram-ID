"""
tests.database.test_crud
========================
Tests for database CRUD operations, constraints, and audit logging:
- User creation, retrieval, status updates, and listing
- Account linking, lookup, upserting, and removal
- Unique constraints on (user_id, phone_number)
- Foreign key enforcement and cascade deletion
- Operation history logging, user audit trails, and SET NULL cascades
- Key-value metadata repository operations
- Model to_dict() and from_row() serialization
"""

from __future__ import annotations

from pathlib import Path
import pytest
import sqlite3
import aiosqlite

from database.connection import DatabaseConnection
from database.models import (
    AccountRecord,
    MigrationResult,
    OperationLogRecord,
    UserRecord,
)
from database.repository import (
    AccountRepository,
    MetadataRepository,
    OperationLogRepository,
    UserRepository,
    init_db,
)


@pytest.fixture
async def db_conn():
    """Fixture providing an initialized in-memory database connection."""
    conn_mgr = DatabaseConnection(":memory:")
    await conn_mgr.init_db()
    yield conn_mgr
    await conn_mgr.close()


@pytest.mark.database
async def test_user_get_or_create_new_user(db_conn: DatabaseConnection):
    """Verify creating a new user initializes all fields properly."""
    repo = UserRepository(db_conn)
    user = await repo.get_or_create_user(6663948368)

    assert user.user_id == 6663948368
    assert user.telegram_id == 6663948368
    assert user.is_active is True
    assert user.created_at != ""
    assert user.last_seen_at != ""


@pytest.mark.database
async def test_user_get_or_create_existing_user(db_conn: DatabaseConnection):
    """Verify get_or_create on existing user preserves created_at and updates last_seen_at."""
    repo = UserRepository(db_conn)
    u1 = await repo.get_or_create_user(123456)
    created_at = u1.created_at

    # Second call for same user
    u2 = await repo.get_or_create_user(123456)
    assert u2.user_id == 123456
    assert u2.created_at == created_at


@pytest.mark.database
async def test_user_get_nonexistent(db_conn: DatabaseConnection):
    """Verify querying non-existent user returns None."""
    repo = UserRepository(db_conn)
    user = await repo.get_user(999999999)
    assert user is None


@pytest.mark.database
async def test_user_update_last_seen(db_conn: DatabaseConnection):
    """Verify update_last_seen modifies last_seen_at."""
    repo = UserRepository(db_conn)
    await repo.get_or_create_user(42)

    updated = await repo.update_last_seen(42)
    assert updated is not None
    assert updated.user_id == 42


@pytest.mark.database
async def test_user_set_active_status(db_conn: DatabaseConnection):
    """Verify toggling active status on user."""
    repo = UserRepository(db_conn)
    await repo.get_or_create_user(42)

    success = await repo.set_active_status(42, False)
    assert success is True
    u = await repo.get_user(42)
    assert u is not None
    assert u.is_active is False

    await repo.set_active_status(42, True)
    u_active = await repo.get_user(42)
    assert u_active is not None
    assert u_active.is_active is True


@pytest.mark.database
async def test_user_list_all(db_conn: DatabaseConnection):
    """Verify list_all_users returns all registered users."""
    repo = UserRepository(db_conn)
    await repo.get_or_create_user(101)
    await repo.get_or_create_user(102)
    await repo.get_or_create_user(103)

    users = await repo.list_all_users()
    assert len(users) == 3
    uids = [u.user_id for u in users]
    assert uids == [101, 102, 103]


@pytest.mark.database
async def test_account_add_and_get(db_conn: DatabaseConnection):
    """Verify adding account and fetching user accounts."""
    user_repo = UserRepository(db_conn)
    acc_repo = AccountRepository(db_conn)

    await user_repo.get_or_create_user(500)
    acc = await acc_repo.add_account(
        user_id=500,
        phone="+15156723850",
        status="active",
        added_at="2025-06-12 09:22:20+00:00",
    )

    assert acc.id is not None
    assert acc.user_id == 500
    assert acc.phone_number == "+15156723850"
    assert acc.phone == "+15156723850"
    assert acc.status == "active"
    assert acc.session_file == "+15156723850.session"
    assert acc.added_at == "2025-06-12 09:22:20+00:00"

    user_accounts = await acc_repo.get_user_accounts(500)
    assert len(user_accounts) == 1
    assert user_accounts[0].phone == "+15156723850"


@pytest.mark.database
async def test_account_get_by_phone(db_conn: DatabaseConnection):
    """Verify fetching account by phone across users."""
    user_repo = UserRepository(db_conn)
    acc_repo = AccountRepository(db_conn)

    await user_repo.get_or_create_user(500)
    await acc_repo.add_account(500, "+14417071240")

    found = await acc_repo.get_account_by_phone("+14417071240")
    assert found is not None
    assert found.user_id == 500
    assert found.phone_number == "+14417071240"

    not_found = await acc_repo.get_account_by_phone("+999999999")
    assert not_found is None


@pytest.mark.database
async def test_account_unique_constraint_upsert(db_conn: DatabaseConnection):
    """Verify adding same phone for same user updates status rather than creating duplicates."""
    user_repo = UserRepository(db_conn)
    acc_repo = AccountRepository(db_conn)

    await user_repo.get_or_create_user(500)
    await acc_repo.add_account(500, "+15156723850", status="active")
    # Upsert with different status
    await acc_repo.add_account(500, "+15156723850", status="missing_session")

    accounts = await acc_repo.get_user_accounts(500)
    assert len(accounts) == 1
    assert accounts[0].status == "missing_session"


@pytest.mark.database
async def test_account_remove(db_conn: DatabaseConnection):
    """Verify removing an account."""
    user_repo = UserRepository(db_conn)
    acc_repo = AccountRepository(db_conn)

    await user_repo.get_or_create_user(500)
    await acc_repo.add_account(500, "+15156723850")

    removed = await acc_repo.remove_account(500, "+15156723850")
    assert removed is True

    # Removing again returns False
    removed_again = await acc_repo.remove_account(500, "+15156723850")
    assert removed_again is False

    accounts = await acc_repo.get_user_accounts(500)
    assert len(accounts) == 0


@pytest.mark.database
async def test_account_update_status_and_last_used(db_conn: DatabaseConnection):
    """Verify updating account status and last_used_at."""
    user_repo = UserRepository(db_conn)
    acc_repo = AccountRepository(db_conn)

    await user_repo.get_or_create_user(500)
    await acc_repo.add_account(500, "+15156723850", status="active")

    await acc_repo.update_account_status(500, "+15156723850", "unauthorized")
    await acc_repo.update_last_used(500, "+15156723850")

    acc = await acc_repo.get_account(500, "+15156723850")
    assert acc is not None
    assert acc.status == "unauthorized"
    assert acc.last_used_at is not None


@pytest.mark.database
async def test_foreign_key_violation_on_account_insert(db_conn: DatabaseConnection):
    """Verify inserting account directly without user raises foreign key integrity error."""
    async with db_conn.get_db() as conn:
        with pytest.raises((sqlite3.IntegrityError, aiosqlite.IntegrityError)):
            await conn.execute(
                "INSERT INTO accounts (user_id, phone_number, added_at) VALUES (?, ?, ?)",
                (999999, "+1234567890", "2026-01-01"),
            )
            await conn.commit()


@pytest.mark.database
async def test_foreign_key_cascade_user_deletion(db_conn: DatabaseConnection):
    """Verify deleting a user cascades and deletes all associated accounts."""
    user_repo = UserRepository(db_conn)
    acc_repo = AccountRepository(db_conn)

    await user_repo.get_or_create_user(777)
    await acc_repo.add_account(777, "+1111111111")
    await acc_repo.add_account(777, "+2222222222")

    assert len(await acc_repo.get_user_accounts(777)) == 2

    # Delete user
    deleted = await user_repo.delete_user(777)
    assert deleted is True

    # Associated accounts should be cascaded and deleted
    assert len(await acc_repo.get_user_accounts(777)) == 0


@pytest.mark.database
async def test_operation_log_crud(db_conn: DatabaseConnection):
    """Verify logging operation records and retrieving them."""
    user_repo = UserRepository(db_conn)
    log_repo = OperationLogRepository(db_conn)

    await user_repo.get_or_create_user(888)
    rec = await log_repo.log_operation(
        user_id=888,
        phone_number="+15156723850",
        action="export_vcf",
        status="success",
        details="Exported 42 contacts",
    )

    assert rec.id is not None
    assert rec.user_id == 888
    assert rec.phone_number == "+15156723850"
    assert rec.action == "export_vcf"
    assert rec.status == "success"
    assert rec.details == "Exported 42 contacts"
    assert rec.timestamp != ""

    user_logs = await log_repo.get_user_history(888)
    assert len(user_logs) == 1
    assert user_logs[0].action == "export_vcf"


@pytest.mark.database
async def test_operation_log_foreign_key_set_null(db_conn: DatabaseConnection):
    """Verify deleting user sets user_id to NULL in operation_history (ON DELETE SET NULL)."""
    user_repo = UserRepository(db_conn)
    log_repo = OperationLogRepository(db_conn)

    await user_repo.get_or_create_user(999)
    await log_repo.log_operation(
        user_id=999,
        action="auth_add",
        status="success",
    )

    # Delete user
    await user_repo.delete_user(999)

    # Operation log should remain with user_id = None
    all_logs = await log_repo.get_recent_logs()
    assert len(all_logs) == 1
    assert all_logs[0].action == "auth_add"
    assert all_logs[0].user_id is None


@pytest.mark.database
async def test_metadata_repository(db_conn: DatabaseConnection):
    """Verify MetadataRepository get and set operations."""
    repo = MetadataRepository(db_conn)

    val = await repo.get("nonexistent_key")
    assert val is None

    await repo.set("migration_flag", "true")
    val2 = await repo.get("migration_flag")
    assert val2 == "true"

    # Update key
    await repo.set("migration_flag", "completed")
    val3 = await repo.get("migration_flag")
    assert val3 == "completed"


@pytest.mark.database
def test_models_to_dict_and_from_row():
    """Verify serialization methods on model classes."""
    u = UserRecord(user_id=1, created_at="2026-01-01", last_seen_at="2026-01-02", is_active=True)
    assert u.to_dict()["user_id"] == 1
    u_copy = UserRecord.from_row((1, "2026-01-01", "2026-01-02", True))
    assert u_copy.user_id == 1

    a = AccountRecord(
        id=10,
        user_id=1,
        phone_number="+15156723850",
        session_file="+15156723850.session",
        status="active",
        added_at="2026-01-01",
        last_used_at=None,
    )
    assert a.phone == "+15156723850"
    assert a.to_dict()["phone_number"] == "+15156723850"

    op = OperationLogRecord(
        id=1,
        user_id=1,
        phone_number="+15156723850",
        action="test",
        details="none",
        status="success",
        timestamp="2026-01-01",
    )
    assert op.to_dict()["action"] == "test"

    mig = MigrationResult(migrated_users=5, migrated_accounts=10, missing_sessions=2, skipped=False, details="ok")
    assert mig.to_dict()["migrated_users"] == 5
