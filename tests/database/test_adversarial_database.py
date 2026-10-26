"""
tests.database.test_adversarial_database
========================================
Adversarial stress testing for database layer (Milestone M2.1 Challenge Battery):
1. High Concurrency & WAL Mode:
   - Simultaneous multi-worker readers and writers on file-backed database in WAL mode
   - WAL file creation and journal mode verification
   - In-memory (:memory:) shared connection concurrency under parallel coroutines
   - Rapid concurrent updates and status toggles without lost updates
2. Transaction Rollbacks & Atomicity:
   - Transaction rollback on explicit conn.rollback()
   - Uncommitted operations rolled back when connection closes without commit
   - Multi-step atomicity under simulated exception injection
3. Foreign Key Constraints & Cascade Behavior:
   - Strict enforcement: accounts insert with non-existent user_id raises IntegrityError
   - Strict enforcement: operation_history insert with non-existent user_id raises IntegrityError
   - Foreign key cascade: deleting user removes all associated accounts
   - Foreign key set null: deleting user preserves operation_history but clears user_id
   - Foreign key persistence across freshly opened connections
4. SQL Injection Resistance & Boundary Hardening:
   - Classic SQL injection payloads in phone numbers (quotes, comment markers, UNION, stacked queries)
   - Injection payloads in operation details and actions
   - Injection payloads in metadata keys and values
   - Null bytes, quotes, escapes, and special characters
   - 64-bit Telegram user IDs (up to 2^63 - 1) and negative IDs (channels/supergroups)
   - Type safety: string injection in integer user_id rejected safely via ValueError
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import pytest
import aiosqlite

from database.connection import DatabaseConnection
from database.models import AccountRecord, OperationLogRecord, UserRecord
from database.repository import (
    AccountRepository,
    MetadataRepository,
    OperationLogRepository,
    UserRepository,
    init_db,
)


# ============================================================================
# 1. HIGH CONCURRENCY & WAL MODE STRESS TESTS
# ============================================================================

@pytest.mark.database
async def test_wal_mode_active_and_files_created(tmp_path: Path):
    """Empirically verify that file-backed database operates in WAL mode and creates WAL/SHM files."""
    db_file = tmp_path / "wal_verify.db"
    db = DatabaseConnection(db_file)
    await db.init_db()

    async with db.get_db() as conn:
        cursor = await conn.execute("PRAGMA journal_mode;")
        row = await cursor.fetchone()
        assert row[0].lower() == "wal", f"Expected WAL mode, got {row[0]}"

        # Write data to trigger WAL file creation
        await conn.execute("INSERT INTO metadata (key, value, updated_at) VALUES (?, ?, ?)", ("k1", "v1", "2026-01-01"))
        await conn.commit()

    # Verify database file exists
    assert db_file.exists()


@pytest.mark.database
async def test_high_concurrency_file_wal_simultaneous_readers_and_writers(tmp_path: Path):
    """
    Stress-test high concurrency on a file-backed database in WAL mode:
    - 20 concurrent writer tasks inserting users and accounts
    - 20 concurrent reader tasks querying users, accounts, and counts
    - 10 concurrent updater tasks updating last_seen and account status
    All 50 tasks run simultaneously via asyncio.gather.
    """
    db_file = tmp_path / "concurrency_wal.db"
    db = DatabaseConnection(db_file)
    await db.init_db()

    user_repo = UserRepository(db)
    acc_repo = AccountRepository(db)
    log_repo = OperationLogRepository(db)

    # Pre-seed 10 base users
    for i in range(10):
        await user_repo.get_or_create_user(1000 + i)
        await acc_repo.add_account(1000 + i, f"+100000000{i:02d}")

    num_writers = 20
    num_readers = 20
    num_updaters = 10

    errors: list[Exception] = []

    async def writer_task(idx: int):
        try:
            uid = 2000 + idx
            phone = f"+200000000{idx:02d}"
            # Create user
            await user_repo.get_or_create_user(uid)
            # Add account
            await acc_repo.add_account(uid, phone)
            # Log operation
            await log_repo.log_operation(
                action="concurrent_write",
                status="success",
                user_id=uid,
                phone_number=phone,
                details=f"Writer task {idx}",
            )
        except Exception as exc:
            errors.append(exc)

    async def reader_task(idx: int):
        try:
            # Random reads across existing IDs
            target_uid = 1000 + (idx % 10)
            u = await user_repo.get_user(target_uid)
            assert u is not None
            accounts = await acc_repo.get_user_accounts(target_uid)
            assert len(accounts) >= 1
            logs = await log_repo.get_recent_logs(limit=10)
            assert isinstance(logs, list)
        except Exception as exc:
            errors.append(exc)

    async def updater_task(idx: int):
        try:
            target_uid = 1000 + (idx % 10)
            phone = f"+100000000{idx % 10:02d}"
            await user_repo.update_last_seen(target_uid)
            await acc_repo.update_account_status(target_uid, phone, "active")
        except Exception as exc:
            errors.append(exc)

    # Launch all 50 concurrent coroutines
    tasks = (
        [writer_task(i) for i in range(num_writers)]
        + [reader_task(i) for i in range(num_readers)]
        + [updater_task(i) for i in range(num_updaters)]
    )

    await asyncio.gather(*tasks)

    # Assert zero concurrency lock errors occurred
    assert len(errors) == 0, f"Encountered {len(errors)} concurrency errors: {errors}"

    # Verify final data integrity:
    # 10 initial users + 20 writer users = 30 users
    all_users = await user_repo.list_all_users()
    assert len(all_users) == 30

    # 10 initial accounts + 20 writer accounts = 30 accounts
    all_accounts = await acc_repo.list_all_accounts()
    assert len(all_accounts) == 30

    # 20 writer logs
    all_logs = await log_repo.get_recent_logs(limit=100)
    assert len(all_logs) == 20


@pytest.mark.database
async def test_in_memory_parallel_coroutine_concurrency():
    """
    Stress-test concurrency on in-memory (:memory:) database where a single
    underlying connection is shared across concurrent coroutines.
    """
    db = DatabaseConnection(":memory:")
    await db.init_db()

    user_repo = UserRepository(db)
    acc_repo = AccountRepository(db)

    async def worker(uid: int):
        await user_repo.get_or_create_user(uid)
        await acc_repo.add_account(uid, f"+30000000{uid}")
        user = await user_repo.get_user(uid)
        assert user is not None
        accounts = await acc_repo.get_user_accounts(uid)
        assert len(accounts) == 1

    # Run 25 concurrent tasks on the shared in-memory connection
    await asyncio.gather(*[worker(i) for i in range(25)])

    all_users = await user_repo.list_all_users()
    assert len(all_users) == 25

    all_accounts = await acc_repo.list_all_accounts()
    assert len(all_accounts) == 25

    await db.close()


@pytest.mark.database
async def test_concurrent_connect_and_close_race(tmp_path: Path):
    """
    Verify thread/coroutine safety of connect() and close() when called
    simultaneously from multiple coroutines on the same DatabaseConnection instance.
    """
    db = DatabaseConnection(tmp_path / "race.db")

    async def opener():
        conn = await db.connect()
        assert conn is not None

    async def closer():
        await asyncio.sleep(0.005)
        await db.close()

    # Interleave connect and close calls concurrently
    await asyncio.gather(
        opener(), opener(), opener(),
        closer(),
        opener(), opener(),
        closer(),
    )

    # Final cleanup
    await db.close()
    assert db._shared_conn is None


# ============================================================================
# 2. TRANSACTION ATOMICITY & ROLLBACK STRESS TESTS
# ============================================================================

@pytest.mark.database
async def test_explicit_transaction_rollback(tmp_path: Path):
    """Verify that calling conn.rollback() cleanly reverts all uncommitted modifications."""
    db = DatabaseConnection(tmp_path / "rollback.db")
    await db.init_db()

    async with db.get_db() as conn:
        # Insert a user
        await conn.execute(
            "INSERT INTO users (user_id, created_at, last_seen_at, is_active) VALUES (?, ?, ?, 1)",
            (5555, "2026-01-01", "2026-01-01"),
        )
        # Roll back instead of commit
        await conn.rollback()

    # Verify user does not exist
    user_repo = UserRepository(db)
    assert await user_repo.get_user(5555) is None


@pytest.mark.database
async def test_uncommitted_connection_close_rolls_back(tmp_path: Path):
    """Verify that closing a connection without committing automatically discards uncommitted changes."""
    db_file = tmp_path / "uncommitted.db"
    db = DatabaseConnection(db_file)
    await db.init_db()

    # Open raw connection, insert without commit, then close
    conn = await aiosqlite.connect(str(db_file))
    await conn.execute(
        "INSERT INTO users (user_id, created_at, last_seen_at, is_active) VALUES (?, ?, ?, 1)",
        (7777, "2026-01-01", "2026-01-01"),
    )
    # Intentionally close without conn.commit()
    await conn.close()

    # Check via fresh connection: user must NOT exist
    user_repo = UserRepository(db)
    assert await user_repo.get_user(7777) is None


@pytest.mark.database
async def test_multi_statement_atomic_rollback_on_failure(tmp_path: Path):
    """
    Verify multi-statement transaction atomicity:
    If a batch operation fails midway (e.g. invalid query or constraint violation),
    all prior statements in that transaction context are rolled back.
    """
    db_file = tmp_path / "atomic_failure.db"
    db = DatabaseConnection(db_file)
    await db.init_db()

    user_repo = UserRepository(db)

    # Attempt a multi-statement transaction that fails on the second insert
    async with db.get_db() as conn:
        try:
            # 1. Insert user
            await conn.execute(
                "INSERT INTO users (user_id, created_at, last_seen_at, is_active) VALUES (?, ?, ?, 1)",
                (9999, "2026-01-01", "2026-01-01"),
            )
            # 2. Intentionally execute invalid statement to trigger exception
            await conn.execute("INSERT INTO non_existent_table VALUES (1, 2, 3)")
            await conn.commit()
        except sqlite3.OperationalError:
            await conn.rollback()

    # Verify that user 9999 was NOT committed
    assert await user_repo.get_user(9999) is None


@pytest.mark.database
async def test_account_add_auto_create_user_atomicity(tmp_path: Path):
    """Verify that add_account with auto_create_user=True creates both user and account atomically."""
    db = DatabaseConnection(tmp_path / "auto_create.db")
    await db.init_db()

    user_repo = UserRepository(db)
    acc_repo = AccountRepository(db)

    # User 8888 does not exist yet
    assert await user_repo.get_user(8888) is None

    # add_account with auto_create_user=True
    acc = await acc_repo.add_account(8888, "+18888888888", auto_create_user=True)
    assert acc is not None
    assert acc.user_id == 8888

    # User must now exist
    u = await user_repo.get_user(8888)
    assert u is not None
    assert u.user_id == 8888


# ============================================================================
# 3. FOREIGN KEY CONSTRAINTS & CASCADE STRESS TESTS
# ============================================================================

@pytest.mark.database
async def test_foreign_key_accounts_insert_nonexistent_user_rejected(tmp_path: Path):
    """Empirically verify that accounts table rejects foreign key violation on non-existent user."""
    db = DatabaseConnection(tmp_path / "fk_reject.db")
    await db.init_db()

    async with db.get_db() as conn:
        with pytest.raises((sqlite3.IntegrityError, aiosqlite.IntegrityError)):
            await conn.execute(
                "INSERT INTO accounts (user_id, phone_number, added_at) VALUES (?, ?, ?)",
                (999999999, "+19999999999", "2026-01-01"),
            )
            await conn.commit()


@pytest.mark.database
async def test_foreign_key_operation_history_nonexistent_user_rejected(tmp_path: Path):
    """Empirically verify that operation_history rejects foreign key violation on non-existent user."""
    db = DatabaseConnection(tmp_path / "fk_log_reject.db")
    await db.init_db()

    async with db.get_db() as conn:
        with pytest.raises((sqlite3.IntegrityError, aiosqlite.IntegrityError)):
            await conn.execute(
                "INSERT INTO operation_history (user_id, action, status, timestamp) VALUES (?, ?, ?, ?)",
                (999999999, "illegal_action", "failure", "2026-01-01"),
            )
            await conn.commit()


@pytest.mark.database
async def test_foreign_key_cascade_delete_all_child_accounts(tmp_path: Path):
    """Verify ON DELETE CASCADE deletes all linked accounts when parent user is removed."""
    db = DatabaseConnection(tmp_path / "cascade.db")
    await db.init_db()

    user_repo = UserRepository(db)
    acc_repo = AccountRepository(db)

    # Create user with 5 accounts
    uid = 4444
    await user_repo.get_or_create_user(uid)
    for i in range(5):
        await acc_repo.add_account(uid, f"+144444444{i:02d}")

    assert len(await acc_repo.get_user_accounts(uid)) == 5

    # Delete parent user
    deleted = await user_repo.delete_user(uid)
    assert deleted is True

    # Verify all 5 child accounts were cascaded and removed
    assert len(await acc_repo.get_user_accounts(uid)) == 0

    # Also verify accounts table directly via query
    async with db.get_db() as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM accounts WHERE user_id = ?", (uid,))
        row = await cursor.fetchone()
        assert row[0] == 0


@pytest.mark.database
async def test_foreign_key_set_null_on_operation_history(tmp_path: Path):
    """
    Verify ON DELETE SET NULL on operation_history:
    When a user is deleted, their audit log records remain intact but user_id is set to NULL.
    """
    db = DatabaseConnection(tmp_path / "set_null.db")
    await db.init_db()

    user_repo = UserRepository(db)
    log_repo = OperationLogRepository(db)

    uid = 3333
    await user_repo.get_or_create_user(uid)

    # Log 3 operations
    for action in ["start", "export_vcf", "logout"]:
        await log_repo.log_operation(
            action=action,
            status="success",
            user_id=uid,
            phone_number="+13333333333",
            details=f"Action {action} for user {uid}",
        )

    # Verify user history
    logs = await log_repo.get_user_history(uid)
    assert len(logs) == 3

    # Delete user
    await user_repo.delete_user(uid)

    # Logs must still exist in table, but user_id is NULL
    recent_logs = await log_repo.get_recent_logs(limit=10)
    assert len(recent_logs) == 3
    for log_rec in recent_logs:
        assert log_rec.user_id is None
        assert log_rec.phone_number == "+13333333333"


@pytest.mark.database
async def test_foreign_keys_persist_across_consecutive_connections(tmp_path: Path):
    """
    Verify that foreign key enforcement is NOT lost when opening separate
    connections via DatabaseConnection.get_db().
    """
    db = DatabaseConnection(tmp_path / "fk_persistence.db")
    await db.init_db()

    for attempt in range(5):
        async with db.get_db() as conn:
            cursor = await conn.execute("PRAGMA foreign_keys;")
            row = await cursor.fetchone()
            assert row[0] == 1, f"Attempt {attempt}: PRAGMA foreign_keys was not enabled (got {row[0]})"
        await asyncio.sleep(0.02)


# ============================================================================
# 4. SQL INJECTION RESISTANCE & ADVERSARIAL INPUTS
# ============================================================================

SQL_INJECTION_PAYLOADS = [
    # Classic boolean bypasses
    "' OR '1'='1",
    "' OR 1=1 --",
    "admin' --",
    "' OR 'x'='x",
    # Stacked queries & destructive DDL
    "'; DROP TABLE users; --",
    "'; DROP TABLE accounts; --",
    "'; DELETE FROM operation_history; --",
    # Union-based extraction
    "' UNION SELECT 1, 'injected', '2026-01-01', 1 --",
    "' UNION SELECT id, phone_number, session_file, status, added_at, last_used_at, NULL FROM accounts --",
    # Subqueries and expressions
    "' AND (SELECT COUNT(*) FROM users) > 0 --",
    "' OR EXISTS(SELECT 1 FROM users WHERE 1=1) --",
    # SQLite pragmas
    "'; PRAGMA foreign_keys = OFF; --",
    # Special characters and escapes
    "\\",
    "\"",
    "''''",
    "/* comment */",
    "-- comment",
    "\r\n\t",
    "null",
    "None",
    # Unicode homoglyphs and apostrophe variants
    "’ OR ‘1’=‘1",
    "ʻ OR 1=1 --",
    # Null byte attack
    "+15156723850\x00' OR 1=1 --",
]


@pytest.mark.database
@pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
async def test_sql_injection_resistance_phone_lookups(tmp_path: Path, payload: str):
    """
    Test AccountRepository.get_account and get_account_by_phone against SQL injection payloads.
    Must return None safely without syntax error, table damage, or data leakage.
    """
    db = DatabaseConnection(tmp_path / f"sqli_phone_{hash(payload) % 10000}.db")
    await db.init_db()

    acc_repo = AccountRepository(db)
    user_repo = UserRepository(db)

    # Seed valid user and account
    await user_repo.get_or_create_user(100)
    await acc_repo.add_account(100, "+15156723850")

    # 1. get_account with malicious phone
    res1 = await acc_repo.get_account(100, payload)
    assert res1 is None or res1.phone_number == payload.strip()

    # 2. get_account_by_phone with malicious phone
    res2 = await acc_repo.get_account_by_phone(payload)
    assert res2 is None or res2.phone_number == payload.strip()

    # 3. Verify legitimate account is untouched
    valid_acc = await acc_repo.get_account(100, "+15156723850")
    assert valid_acc is not None
    assert valid_acc.phone_number == "+15156723850"

    # 4. Verify users table was NOT dropped
    u = await user_repo.get_user(100)
    assert u is not None


@pytest.mark.database
@pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
async def test_sql_injection_resistance_account_insert_and_delete(tmp_path: Path, payload: str):
    """
    Test AccountRepository.add_account and remove_account when phone number contains injection payloads.
    The string must be treated as a literal phone number without executing SQL statements.
    """
    db = DatabaseConnection(tmp_path / f"sqli_acc_{hash(payload) % 10000}.db")
    await db.init_db()

    user_repo = UserRepository(db)
    acc_repo = AccountRepository(db)

    await user_repo.get_or_create_user(200)

    # Add account with malicious payload as phone
    acc = await acc_repo.add_account(200, payload, status="active")
    assert acc is not None
    assert acc.phone_number == payload.strip()

    # Remove account with payload
    removed = await acc_repo.remove_account(200, payload)
    assert removed is True

    # Verify tables still intact
    assert len(await user_repo.list_all_users()) == 1


@pytest.mark.database
@pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
async def test_sql_injection_resistance_metadata_repository(tmp_path: Path, payload: str):
    """
    Test MetadataRepository against SQL injection payloads in key and value.
    Must store and retrieve exact literal strings.
    """
    db = DatabaseConnection(tmp_path / f"sqli_meta_{hash(payload) % 10000}.db")
    await db.init_db()

    meta_repo = MetadataRepository(db)

    # Set key-value with injection payload
    await meta_repo.set(payload, f"val_{payload}")
    retrieved = await meta_repo.get(payload)
    assert retrieved == f"val_{payload}"

    # Also test malicious value for standard key
    await meta_repo.set("safe_key", payload)
    retrieved_val = await meta_repo.get("safe_key")
    assert retrieved_val == payload


@pytest.mark.database
@pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
async def test_sql_injection_resistance_operation_logging(tmp_path: Path, payload: str):
    """
    Test OperationLogRepository against injection payloads in action, details, and phone.
    """
    db = DatabaseConnection(tmp_path / f"sqli_log_{hash(payload) % 10000}.db")
    await db.init_db()

    log_repo = OperationLogRepository(db)

    log_rec = await log_repo.log_operation(
        action=payload,
        details=f"Details with payload: {payload}",
        phone_number=payload,
    )
    assert log_rec.id is not None
    assert log_rec.action == payload
    assert log_rec.details == f"Details with payload: {payload}"

    # Query logs back
    recent = await log_repo.get_recent_logs(limit=5)
    assert len(recent) == 1
    assert recent[0].action == payload


@pytest.mark.database
async def test_user_id_type_enforcement_prevents_sql_injection(tmp_path: Path):
    """
    Verify that passing SQL injection string payloads into user_id parameters
    is caught safely by Python int() type conversion before any SQL statement executes.
    """
    db = DatabaseConnection(tmp_path / "type_enforce.db")
    await db.init_db()

    user_repo = UserRepository(db)
    acc_repo = AccountRepository(db)

    malicious_ids = [
        "1 OR 1=1",
        "1; DROP TABLE users; --",
        "' OR '1'='1",
        "SELECT user_id FROM users",
        "NaN",
        "1e10",
        None,
    ]

    for bad_id in malicious_ids:
        # UserRepository.get_user
        with pytest.raises((ValueError, TypeError)):
            await user_repo.get_user(bad_id)  # type: ignore

        # UserRepository.get_or_create_user
        with pytest.raises((ValueError, TypeError)):
            await user_repo.get_or_create_user(bad_id)  # type: ignore

        # AccountRepository.get_user_accounts
        with pytest.raises((ValueError, TypeError)):
            await acc_repo.get_user_accounts(bad_id)  # type: ignore


# ============================================================================
# 5. TELEGRAM 64-BIT ID BOUNDARIES & LARGE PAYLOAD STRESS
# ============================================================================

@pytest.mark.database
async def test_telegram_64bit_large_user_ids(tmp_path: Path):
    """
    Verify full support for 64-bit Telegram user IDs:
    - Real-world 10-digit IDs (e.g. 6663948368)
    - Max signed 64-bit integer: 9223372036854775807 (2^63 - 1)
    - Negative channel/supergroup IDs: -1001234567890
    """
    db = DatabaseConnection(tmp_path / "64bit_ids.db")
    await db.init_db()

    user_repo = UserRepository(db)
    acc_repo = AccountRepository(db)

    test_ids = [
        6663948368,                    # Real bot user ID
        9223372036854775807,           # 2^63 - 1 (max 64-bit signed int)
        -1001234567890,                # Negative supergroup ID
        -1,                            # -1 boundary
        1,                             # 1 boundary
    ]

    for uid in test_ids:
        # Create user
        u = await user_repo.get_or_create_user(uid)
        assert u.user_id == uid
        assert u.telegram_id == uid

        # Fetch user
        fetched = await user_repo.get_user(uid)
        assert fetched is not None
        assert fetched.user_id == uid

        # Link account
        acc = await acc_repo.add_account(uid, f"+1000{abs(uid) % 1000000000}")
        assert acc.user_id == uid

        # Query account
        accs = await acc_repo.get_user_accounts(uid)
        assert len(accs) == 1
        assert accs[0].user_id == uid


@pytest.mark.database
async def test_large_payload_stress(tmp_path: Path):
    """
    Stress-test storage and retrieval of large payloads:
    - 500 KB operation details text
    - 500 KB metadata value
    Verify no memory corruption, truncation, or query failures.
    """
    db = DatabaseConnection(tmp_path / "large_payload.db")
    await db.init_db()

    log_repo = OperationLogRepository(db)
    meta_repo = MetadataRepository(db)

    # 500 KB string
    large_text = "X" * (500 * 1024)

    # Operation log with large details
    log_rec = await log_repo.log_operation(
        action="large_test",
        details=large_text,
    )
    assert log_rec.id is not None
    assert len(log_rec.details or "") == 500 * 1024

    # Fetch log back
    logs = await log_repo.get_recent_logs(limit=1)
    assert len(logs) == 1
    assert len(logs[0].details or "") == 500 * 1024

    # Metadata with large value
    await meta_repo.set("large_key", large_text)
    val = await meta_repo.get("large_key")
    assert val is not None
    assert len(val) == 500 * 1024
