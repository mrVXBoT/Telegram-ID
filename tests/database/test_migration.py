"""
tests.database.test_migration
=============================
Tests for JSON-to-SQLite data migration:
- Lossless user and account migration
- Preservation of original 'added_at' timestamps
- Accurate detection of missing .session files vs active sessions
- Automatic creation of .bak backup file
- Idempotency across repeated executions (safe merge without duplicates)
- Graceful handling of missing, empty, corrupt, or invalid JSON structures
- End-to-end verification against real repository sample files
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import pytest

from database.connection import DatabaseConnection
from database.migration import auto_migrate, run_migration
from database.models import MigrationResult
from database.repository import AccountRepository, UserRepository


@pytest.fixture
def migration_env(tmp_path: Path):
    """
    Fixture creating temporary workspace with mock user_data.json and sessions directory.
    """
    db_file = tmp_path / "test_migration.db"
    json_file = tmp_path / "user_data.json"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy session files: one present (+15156723850), one missing (+989999202880)
    (sessions_dir / "+15156723850.session").write_text("dummy-session-1")
    (sessions_dir / "+14417071240.session").write_text("dummy-session-2")

    mock_json_content = {
        "6663948368": {
            "accounts": {
                "+15156723850": {"added_at": "2025-06-12 09:22:20+00:00"},
                "+14417071240": {"added_at": "2025-08-20 20:26:22+00:00"},
                "+989999202880": {"added_at": "2025-08-20 20:29:27+00:00"},
            }
        },
        "7777777777": {
            "accounts": {
                "+19998887777": {"added_at": "2025-09-01 12:00:00+00:00"},
            }
        },
    }
    json_file.write_text(json.dumps(mock_json_content), encoding="utf-8")

    return {
        "db_file": db_file,
        "json_file": json_file,
        "sessions_dir": sessions_dir,
    }


@pytest.mark.database
async def test_migration_successful(migration_env: dict[str, Path]):
    """Verify standard migration creates users, accounts, and marks missing session status correctly."""
    db_file = migration_env["db_file"]
    json_file = migration_env["json_file"]
    sessions_dir = migration_env["sessions_dir"]

    result = await run_migration(db_file, json_file, sessions_dir)

    assert isinstance(result, MigrationResult)
    assert result.skipped is False
    assert result.migrated_users == 2
    assert result.migrated_accounts == 4
    # Out of 4 accounts, 2 have session files (+15156723850, +14417071240) and 2 are missing (+989999202880, +19998887777)
    assert result.missing_sessions == 2

    # Verify database contents
    db = DatabaseConnection(db_file)
    user_repo = UserRepository(db)
    acc_repo = AccountRepository(db)

    u1 = await user_repo.get_user(6663948368)
    assert u1 is not None
    assert u1.user_id == 6663948368

    accounts_u1 = await acc_repo.get_user_accounts(6663948368)
    assert len(accounts_u1) == 3

    acc_map = {a.phone: a for a in accounts_u1}
    assert acc_map["+15156723850"].status == "active"
    assert acc_map["+14417071240"].status == "active"
    assert acc_map["+989999202880"].status == "missing_session"

    await db.close()


@pytest.mark.database
async def test_migration_preserves_added_at_timestamp(migration_env: dict[str, Path]):
    """Verify original added_at timestamp string is preserved exactly."""
    db_file = migration_env["db_file"]
    json_file = migration_env["json_file"]
    sessions_dir = migration_env["sessions_dir"]

    await run_migration(db_file, json_file, sessions_dir)

    db = DatabaseConnection(db_file)
    acc_repo = AccountRepository(db)
    acc = await acc_repo.get_account(6663948368, "+15156723850")
    assert acc is not None
    assert acc.added_at == "2025-06-12 09:22:20+00:00"

    await db.close()


@pytest.mark.database
async def test_migration_creates_backup_file(migration_env: dict[str, Path]):
    """Verify user_data.json.bak is created upon successful migration."""
    db_file = migration_env["db_file"]
    json_file = migration_env["json_file"]
    sessions_dir = migration_env["sessions_dir"]

    bak_file = json_file.with_name(json_file.name + ".bak")
    assert not bak_file.exists()

    await run_migration(db_file, json_file, sessions_dir)

    assert bak_file.exists()
    assert bak_file.read_text(encoding="utf-8") == json_file.read_text(encoding="utf-8")


@pytest.mark.database
async def test_migration_idempotent_repeated_runs(migration_env: dict[str, Path]):
    """Verify running migration repeatedly does not crash or duplicate records."""
    db_file = migration_env["db_file"]
    json_file = migration_env["json_file"]
    sessions_dir = migration_env["sessions_dir"]

    # First run
    res1 = await run_migration(db_file, json_file, sessions_dir)
    assert res1.migrated_users == 2
    assert res1.migrated_accounts == 4

    # Second run
    res2 = await run_migration(db_file, json_file, sessions_dir)
    assert res2.migrated_users == 2
    assert res2.migrated_accounts == 4
    assert res2.skipped is False

    # Check total accounts in DB remains 4
    db = DatabaseConnection(db_file)
    acc_repo = AccountRepository(db)
    all_accounts = await acc_repo.list_all_accounts()
    assert len(all_accounts) == 4

    await db.close()


@pytest.mark.database
async def test_migration_missing_json_file(tmp_path: Path):
    """Verify migration handles non-existent JSON file gracefully."""
    db_file = tmp_path / "test_nonexistent.db"
    missing_json = tmp_path / "nonexistent.json"
    sessions_dir = tmp_path / "sessions"

    res = await run_migration(db_file, missing_json, sessions_dir)
    assert res.skipped is True
    assert res.migrated_users == 0
    assert "does not exist" in res.details


@pytest.mark.database
async def test_migration_empty_json_file(tmp_path: Path):
    """Verify migration handles 0-byte JSON file gracefully."""
    db_file = tmp_path / "test_empty.db"
    empty_json = tmp_path / "empty.json"
    empty_json.write_text("", encoding="utf-8")
    sessions_dir = tmp_path / "sessions"

    res = await run_migration(db_file, empty_json, sessions_dir)
    assert res.skipped is True
    assert "empty" in res.details.lower()


@pytest.mark.database
async def test_migration_corrupt_json_file(tmp_path: Path):
    """Verify migration handles malformed JSON file without throwing unhandled exceptions."""
    db_file = tmp_path / "test_corrupt.db"
    corrupt_json = tmp_path / "corrupt.json"
    corrupt_json.write_text("{broken json: [1, 2, 3", encoding="utf-8")
    sessions_dir = tmp_path / "sessions"

    res = await run_migration(db_file, corrupt_json, sessions_dir)
    assert res.skipped is True
    assert "corrupt" in res.details.lower()


@pytest.mark.database
async def test_migration_non_dict_json(tmp_path: Path):
    """Verify migration handles JSON root that is a list rather than an object."""
    db_file = tmp_path / "test_list.db"
    list_json = tmp_path / "list.json"
    list_json.write_text("[1, 2, 3]", encoding="utf-8")
    sessions_dir = tmp_path / "sessions"

    res = await run_migration(db_file, list_json, sessions_dir)
    assert res.skipped is True
    assert "root must be a json object" in res.details.lower()


@pytest.mark.database
async def test_migration_user_without_accounts(tmp_path: Path):
    """Verify migration handles user object with missing or empty accounts gracefully."""
    db_file = tmp_path / "test_no_acc.db"
    json_file = tmp_path / "no_acc.json"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    content = {
        "12345": {"accounts": {}},
        "67890": {},
        "invalid_id": {"accounts": {"+1234567890": {"added_at": "2026-01-01"}}},
    }
    json_file.write_text(json.dumps(content), encoding="utf-8")

    res = await run_migration(db_file, json_file, sessions_dir)
    assert res.skipped is False
    assert res.migrated_users == 2  # 12345 and 67890, invalid_id skipped
    assert res.migrated_accounts == 0


@pytest.mark.database
async def test_migration_real_repo_files(tmp_path: Path):
    """
    Verify migration against actual snapshot files from Telegram-ID-main if available.
    """
    real_json = Path("Telegram-ID-main/user_data.json")
    real_sessions = Path("Telegram-ID-main/sessions")

    if not real_json.exists() or not real_sessions.exists():
        pytest.skip("Real repo sample files not found at Telegram-ID-main/")

    test_json = tmp_path / "user_data.json"
    shutil.copy2(real_json, test_json)

    db_file = tmp_path / "test_real.db"
    res = await run_migration(db_file, test_json, real_sessions)

    assert res.skipped is False
    assert res.migrated_users == 1
    assert res.migrated_accounts == 3
    # In original user_data.json, +989999202880 is missing from sessions/
    assert res.missing_sessions == 1

    db = DatabaseConnection(db_file)
    acc_repo = AccountRepository(db)
    accounts = await acc_repo.get_user_accounts(6663948368)
    assert len(accounts) == 3

    acc_map = {a.phone: a for a in accounts}
    assert acc_map["+15156723850"].status == "active"
    assert acc_map["+14417071240"].status == "active"
    assert acc_map["+989999202880"].status == "missing_session"

    await db.close()


@pytest.mark.database
async def test_auto_migrate_helper(migration_env: dict[str, Path]):
    """Verify auto_migrate helper function."""
    db_file = migration_env["db_file"]
    json_file = migration_env["json_file"]
    sessions_dir = migration_env["sessions_dir"]

    db_conn = DatabaseConnection(db_file)
    res = await auto_migrate(db_conn, json_path=json_file, sessions_dir=sessions_dir)
    assert res.skipped is False
    assert res.migrated_users == 2

    await db_conn.close()
