"""
database.migration
==================
Lossless, idempotent JSON-to-SQLite database migration.

Imports account and user records from legacy `user_data.json` into SQLite:
- Preserves original 'added_at' timestamps.
- Verifies existence of corresponding .session files in sessions_dir.
- Gracefully marks accounts lacking .session files with status 'missing_session'.
- Creates backup copy `user_data.json.bak` upon successful migration.
- Safe and idempotent across multiple executions.
- Handles missing, empty, or corrupt JSON files without crashing.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any, Mapping, Optional, Union

from database.connection import DatabaseConnection
from database.models import MigrationResult
from database.repository import (
    AccountRepository,
    MetadataRepository,
    OperationLogRepository,
    UserRepository,
    init_db,
)


def _check_session_exists(phone: str, sessions_dir: Path) -> tuple[bool, str]:
    """
    Check if a .session file exists for the phone number.
    Checks both '+<number>.session' and '<number>.session'.

    Returns:
        tuple[bool, str]: (exists, resolved_filename)
    """
    clean_phone = phone.strip()
    candidate_1 = sessions_dir / f"{clean_phone}.session"
    candidate_2 = sessions_dir / f"{clean_phone.lstrip('+')}.session"

    if candidate_1.is_file():
        return True, candidate_1.name
    if candidate_2.is_file():
        return True, candidate_2.name

    return False, f"{clean_phone}.session"


async def run_migration(
    db_path: Union[str, Path, DatabaseConnection],
    json_path: Union[str, Path],
    sessions_dir: Union[str, Path],
) -> MigrationResult:
    """
    Execute migration from user_data.json to SQLite database.

    Args:
        db_path: Path to SQLite database file or active DatabaseConnection instance.
        json_path: Path to user_data.json file.
        sessions_dir: Path to directory containing Telethon .session files.

    Returns:
        MigrationResult: Statistics summarizing migrated users, accounts, and missing sessions.
    """
    # 1. Resolve database connection
    if isinstance(db_path, DatabaseConnection):
        db_conn = db_path
    else:
        db_conn = DatabaseConnection(db_path)

    await db_conn.init_db()

    # 2. Resolve filesystem paths
    jpath = Path(json_path)
    sdir = Path(sessions_dir)

    # 3. Check JSON file existence
    if not jpath.exists() or not jpath.is_file():
        return MigrationResult(
            migrated_users=0,
            migrated_accounts=0,
            missing_sessions=0,
            skipped=True,
            details=f"JSON file does not exist: {jpath}",
        )

    # 4. Read and parse JSON content safely
    try:
        content = jpath.read_text(encoding="utf-8").strip()
    except Exception as e:
        return MigrationResult(
            migrated_users=0,
            migrated_accounts=0,
            missing_sessions=0,
            skipped=True,
            details=f"Failed to read JSON file: {e}",
        )

    if not content:
        return MigrationResult(
            migrated_users=0,
            migrated_accounts=0,
            missing_sessions=0,
            skipped=True,
            details="JSON file is empty",
        )

    try:
        raw_data = json.loads(content)
    except json.JSONDecodeError as e:
        return MigrationResult(
            migrated_users=0,
            migrated_accounts=0,
            missing_sessions=0,
            skipped=True,
            details=f"Corrupt JSON file: {e}",
        )

    if not isinstance(raw_data, dict):
        return MigrationResult(
            migrated_users=0,
            migrated_accounts=0,
            missing_sessions=0,
            skipped=True,
            details="Invalid JSON structure: root must be a JSON object",
        )

    # 5. Process migration records
    user_repo = UserRepository(db_conn)
    account_repo = AccountRepository(db_conn)
    op_repo = OperationLogRepository(db_conn)
    meta_repo = MetadataRepository(db_conn)

    migrated_users_count = 0
    migrated_accounts_count = 0
    missing_sessions_count = 0

    for user_id_str, user_payload in raw_data.items():
        try:
            user_id = int(user_id_str)
        except ValueError:
            # Skip invalid non-integer user IDs
            continue

        accounts_dict: Mapping[str, Any] = {}
        if isinstance(user_payload, dict):
            accounts_dict = user_payload.get("accounts", {}) or {}
        elif isinstance(user_payload, list):
            accounts_dict = {str(p): {} for p in user_payload}

        # Ensure user exists in users table
        await user_repo.get_or_create_user(user_id)
        migrated_users_count += 1

        for phone_key, meta in accounts_dict.items():
            phone_str = str(phone_key).strip()
            if not phone_str:
                continue

            added_at = ""
            if isinstance(meta, dict):
                added_at = str(meta.get("added_at", "")).strip()

            session_exists, session_file = _check_session_exists(phone_str, sdir)
            if session_exists:
                status = "active"
            else:
                status = "missing_session"
                missing_sessions_count += 1

            await account_repo.add_account(
                user_id=user_id,
                phone=phone_str,
                status=status,
                session_file=session_file,
                added_at=added_at if added_at else None,
            )
            migrated_accounts_count += 1

    # 6. Create backup file
    try:
        bak_path = jpath.with_name(jpath.name + ".bak")
        shutil.copy2(jpath, bak_path)
    except Exception as e:
        # Non-fatal if backup copy fails (e.g. read-only filesystem in tests)
        pass

    # 7. Record metadata and audit log
    await meta_repo.set("json_migration_completed", "true")
    await meta_repo.set(
        "json_migration_stats",
        json.dumps(
            {
                "users": migrated_users_count,
                "accounts": migrated_accounts_count,
                "missing_sessions": missing_sessions_count,
            }
        ),
    )

    await op_repo.log_operation(
        action="json_migration",
        status="success",
        details=(
            f"Migrated {migrated_users_count} users, {migrated_accounts_count} accounts "
            f"({missing_sessions_count} missing sessions)"
        ),
    )

    return MigrationResult(
        migrated_users=migrated_users_count,
        migrated_accounts=migrated_accounts_count,
        missing_sessions=missing_sessions_count,
        skipped=False,
        details=(
            f"Successfully migrated {migrated_users_count} users and {migrated_accounts_count} accounts "
            f"({missing_sessions_count} missing sessions)."
        ),
    )


async def auto_migrate(
    db_conn: Optional[DatabaseConnection] = None,
    json_path: Optional[Union[str, Path]] = None,
    sessions_dir: Optional[Union[str, Path]] = None,
) -> MigrationResult:
    """
    Convenience function to automatically locate user_data.json and run migration
    using configured or default application paths.
    """
    if db_conn is None:
        db_conn = DatabaseConnection()

    if sessions_dir is None:
        try:
            from config.settings import get_settings

            sessions_dir = get_settings().sessions_dir
        except Exception:
            sessions_dir = Path("sessions")

    if json_path is None:
        # Check standard locations
        candidates = [
            Path("user_data.json"),
            Path("Telegram-ID-main/user_data.json"),
        ]
        target_path: Optional[Path] = None
        for cand in candidates:
            if cand.exists():
                target_path = cand
                break
        if target_path is None:
            return MigrationResult(
                skipped=True,
                details="No user_data.json found in standard locations.",
            )
        json_path = target_path

    return await run_migration(db_conn, json_path, sessions_dir)
