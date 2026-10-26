"""
database.repository
===================
Asynchronous SQLite CRUD repositories adhering to PROJECT.md interface contracts:
- UserRepository: Management of bot user records
- AccountRepository: Management of linked Telegram accounts
- OperationLogRepository: Operation audit trail logging
- MetadataRepository: Key-value metadata storage (e.g. migration flags)
- init_db: Schema initialization helper
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional, Union

import aiosqlite

from database.models import AccountRecord, OperationLogRecord, UserRecord

if TYPE_CHECKING:
    from database.connection import DatabaseConnection


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    phone_number TEXT NOT NULL,
    session_file TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    added_at TEXT NOT NULL,
    last_used_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, phone_number)
);

CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_phone ON accounts(phone_number);

CREATE TABLE IF NOT EXISTS operation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    phone_number TEXT,
    action TEXT NOT NULL,
    details TEXT,
    status TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_history_user_id ON operation_history(user_id);
CREATE INDEX IF NOT EXISTS idx_history_timestamp ON operation_history(timestamp);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


async def init_db(db_or_conn: Union[aiosqlite.Connection, DatabaseConnection]) -> None:
    """
    Initialize all database tables and indexes if they do not exist.

    Args:
        db_or_conn: Active aiosqlite connection or DatabaseConnection instance.
    """
    if isinstance(db_or_conn, aiosqlite.Connection):
        await db_or_conn.executescript(SCHEMA_SQL)
        await db_or_conn.commit()
    elif hasattr(db_or_conn, "get_db"):
        async with db_or_conn.get_db() as conn:
            await conn.executescript(SCHEMA_SQL)
            await conn.commit()
    else:
        raise TypeError(f"Expected aiosqlite.Connection or DatabaseConnection, got {type(db_or_conn)}")


@asynccontextmanager
async def _resolve_conn(
    db_or_conn: Union[aiosqlite.Connection, DatabaseConnection]
) -> AsyncIterator[aiosqlite.Connection]:
    """Helper context manager to resolve aiosqlite.Connection from connection manager or raw connection."""
    if isinstance(db_or_conn, aiosqlite.Connection):
        yield db_or_conn
    elif hasattr(db_or_conn, "get_db"):
        async with db_or_conn.get_db() as conn:
            yield conn
    else:
        raise TypeError(f"Expected aiosqlite.Connection or DatabaseConnection, got {type(db_or_conn)}")


class UserRepository:
    """
    Repository providing CRUD operations for bot users.
    """

    def __init__(self, db: Union[DatabaseConnection, aiosqlite.Connection]) -> None:
        self.db = db

    async def get_user(self, telegram_id: int) -> Optional[UserRecord]:
        """
        Fetch a user by Telegram ID.

        Args:
            telegram_id: 64-bit Telegram user ID.

        Returns:
            UserRecord if found, None otherwise.
        """
        uid = int(telegram_id)
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "SELECT user_id, created_at, last_seen_at, is_active FROM users WHERE user_id = ?",
                (uid,),
            )
            row = await cursor.fetchone()
            if row is not None:
                return UserRecord.from_row(row)
            return None

    async def get_or_create_user(self, telegram_id: int) -> UserRecord:
        """
        Retrieve an existing user and update their last_seen_at timestamp,
        or create a new user record if they do not exist.

        Args:
            telegram_id: 64-bit Telegram user ID.

        Returns:
            UserRecord: The existing or newly created user.
        """
        uid = int(telegram_id)
        now_str = datetime.now(timezone.utc).isoformat()
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "SELECT user_id, created_at, last_seen_at, is_active FROM users WHERE user_id = ?",
                (uid,),
            )
            row = await cursor.fetchone()
            if row is not None:
                await conn.execute(
                    "UPDATE users SET last_seen_at = ? WHERE user_id = ?",
                    (now_str, uid),
                )
                await conn.commit()
                return UserRecord(
                    user_id=int(row["user_id"]),
                    created_at=str(row["created_at"]),
                    last_seen_at=now_str,
                    is_active=bool(row["is_active"]),
                )

            # Insert new user
            await conn.execute(
                "INSERT INTO users (user_id, created_at, last_seen_at, is_active) VALUES (?, ?, ?, 1)",
                (uid, now_str, now_str),
            )
            await conn.commit()
            return UserRecord(
                user_id=uid,
                created_at=now_str,
                last_seen_at=now_str,
                is_active=True,
            )

    async def update_last_seen(self, telegram_id: int) -> Optional[UserRecord]:
        """Update last_seen_at timestamp for a user."""
        uid = int(telegram_id)
        now_str = datetime.now(timezone.utc).isoformat()
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "UPDATE users SET last_seen_at = ? WHERE user_id = ?",
                (now_str, uid),
            )
            await conn.commit()
            if cursor.rowcount > 0:
                return await self.get_user(uid)
            return None

    async def set_active_status(self, telegram_id: int, is_active: bool) -> bool:
        """Set user active/inactive status."""
        uid = int(telegram_id)
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "UPDATE users SET is_active = ? WHERE user_id = ?",
                (1 if is_active else 0, uid),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def delete_user(self, telegram_id: int) -> bool:
        """
        Delete a user by Telegram ID.
        Associated accounts will cascade-delete automatically.
        """
        uid = int(telegram_id)
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute("DELETE FROM users WHERE user_id = ?", (uid,))
            await conn.commit()
            return cursor.rowcount > 0

    async def list_all_users(self) -> list[UserRecord]:
        """List all registered users ordered by creation date."""
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "SELECT user_id, created_at, last_seen_at, is_active FROM users ORDER BY created_at ASC"
            )
            rows = await cursor.fetchall()
            return [UserRecord.from_row(r) for r in rows]


class AccountRepository:
    """
    Repository providing CRUD operations for linked Telegram accounts.
    """

    def __init__(self, db: Union[DatabaseConnection, aiosqlite.Connection]) -> None:
        self.db = db

    async def get_user_accounts(self, user_id: int) -> list[AccountRecord]:
        """
        Fetch all accounts associated with a bot user.

        Args:
            user_id: Telegram user ID.

        Returns:
            list[AccountRecord]: Ordered by added_at ascending.
        """
        uid = int(user_id)
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "SELECT id, user_id, phone_number, session_file, status, added_at, last_used_at "
                "FROM accounts WHERE user_id = ? ORDER BY added_at ASC",
                (uid,),
            )
            rows = await cursor.fetchall()
            return [AccountRecord.from_row(r) for r in rows]

    async def get_account(self, user_id: int, phone: str) -> Optional[AccountRecord]:
        """
        Fetch a specific account by user ID and phone number.

        Args:
            user_id: Telegram user ID.
            phone: Account phone number.

        Returns:
            AccountRecord if found, None otherwise.
        """
        uid = int(user_id)
        phone_norm = str(phone).strip()
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "SELECT id, user_id, phone_number, session_file, status, added_at, last_used_at "
                "FROM accounts WHERE user_id = ? AND phone_number = ?",
                (uid, phone_norm),
            )
            row = await cursor.fetchone()
            if row is not None:
                return AccountRecord.from_row(row)
            return None

    async def get_account_by_phone(self, phone: str) -> Optional[AccountRecord]:
        """
        Fetch an account record across all users by phone number.

        Args:
            phone: Account phone number.

        Returns:
            AccountRecord if found, None otherwise.
        """
        phone_norm = str(phone).strip()
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "SELECT id, user_id, phone_number, session_file, status, added_at, last_used_at "
                "FROM accounts WHERE phone_number = ? ORDER BY id DESC LIMIT 1",
                (phone_norm,),
            )
            row = await cursor.fetchone()
            if row is not None:
                return AccountRecord.from_row(row)
            return None

    async def add_account(
        self,
        user_id: int,
        phone: str,
        status: str = "active",
        session_file: Optional[str] = None,
        added_at: Optional[str] = None,
        auto_create_user: bool = False,
    ) -> AccountRecord:
        """
        Add or update a linked Telegram account for a user.

        Args:
            user_id: Telegram user ID.
            phone: International format phone number.
            status: Status ('active', 'missing_session', 'unauthorized', etc.).
            session_file: Relative filename of session file (defaults to '{phone}.session').
            added_at: ISO timestamp (defaults to current UTC time).
            auto_create_user: If True, ensures user exists in users table before inserting.

        Returns:
            AccountRecord: The added or updated account.
        """
        uid = int(user_id)
        phone_norm = str(phone).strip()
        timestamp = added_at or datetime.now(timezone.utc).isoformat()
        if session_file is None:
            session_file = f"{phone_norm}.session"

        async with _resolve_conn(self.db) as conn:
            if auto_create_user:
                await conn.execute(
                    "INSERT OR IGNORE INTO users (user_id, created_at, last_seen_at, is_active) VALUES (?, ?, ?, 1)",
                    (uid, timestamp, timestamp),
                )

            cursor = await conn.execute(
                """
                INSERT INTO accounts (user_id, phone_number, session_file, status, added_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(user_id, phone_number) DO UPDATE SET
                    session_file = excluded.session_file,
                    status = excluded.status,
                    added_at = excluded.added_at
                RETURNING id, user_id, phone_number, session_file, status, added_at, last_used_at
                """,
                (uid, phone_norm, session_file, status, timestamp),
            )
            row = await cursor.fetchone()
            await conn.commit()
            if row is None:
                raise RuntimeError("Failed to add or update account")
            return AccountRecord.from_row(row)

    async def remove_account(self, user_id: int, phone: str) -> bool:
        """
        Remove an account by user ID and phone number.

        Args:
            user_id: Telegram user ID.
            phone: Account phone number.

        Returns:
            bool: True if account was found and removed, False otherwise.
        """
        uid = int(user_id)
        phone_norm = str(phone).strip()
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "DELETE FROM accounts WHERE user_id = ? AND phone_number = ?",
                (uid, phone_norm),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def update_account_status(self, user_id: int, phone: str, status: str) -> bool:
        """Update account status (e.g. 'active', 'missing_session', 'unauthorized')."""
        uid = int(user_id)
        phone_norm = str(phone).strip()
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "UPDATE accounts SET status = ? WHERE user_id = ? AND phone_number = ?",
                (status, uid, phone_norm),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def update_last_used(self, user_id: int, phone: str) -> bool:
        """Update last_used_at timestamp to current UTC time."""
        uid = int(user_id)
        phone_norm = str(phone).strip()
        now_str = datetime.now(timezone.utc).isoformat()
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "UPDATE accounts SET last_used_at = ? WHERE user_id = ? AND phone_number = ?",
                (now_str, uid, phone_norm),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def list_all_accounts(self) -> list[AccountRecord]:
        """List all accounts across all users."""
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "SELECT id, user_id, phone_number, session_file, status, added_at, last_used_at "
                "FROM accounts ORDER BY added_at ASC"
            )
            rows = await cursor.fetchall()
            return [AccountRecord.from_row(r) for r in rows]


class OperationLogRepository:
    """
    Repository providing operation history logging and audit trail queries.
    """

    def __init__(self, db: Union[DatabaseConnection, aiosqlite.Connection]) -> None:
        self.db = db

    async def log_operation(
        self,
        action: str,
        status: str = "success",
        user_id: Optional[int] = None,
        phone_number: Optional[str] = None,
        details: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> OperationLogRecord:
        """
        Record an operation event into operation_history.

        Args:
            action: Action identifier (e.g. 'auth_add', 'export_vcf', 'json_migration').
            status: Outcome status ('success', 'failure', 'skipped').
            user_id: Optional user ID.
            phone_number: Optional phone number.
            details: Optional descriptive metadata.
            timestamp: Optional UTC ISO string (defaults to now).

        Returns:
            OperationLogRecord: The inserted log record.
        """
        uid = int(user_id) if user_id is not None else None
        phone_norm = str(phone_number).strip() if phone_number is not None else None
        ts = timestamp or datetime.now(timezone.utc).isoformat()

        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                """
                INSERT INTO operation_history (user_id, phone_number, action, details, status, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id, user_id, phone_number, action, details, status, timestamp
                """,
                (uid, phone_norm, action, details, status, ts),
            )
            row = await cursor.fetchone()
            await conn.commit()
            if row is None:
                raise RuntimeError("Failed to insert operation log")
            return OperationLogRecord.from_row(row)

    async def get_user_history(self, user_id: int, limit: int = 50) -> list[OperationLogRecord]:
        """Fetch operation history for a specific user, newest first."""
        uid = int(user_id)
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "SELECT id, user_id, phone_number, action, details, status, timestamp "
                "FROM operation_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (uid, limit),
            )
            rows = await cursor.fetchall()
            return [OperationLogRecord.from_row(r) for r in rows]

    async def get_recent_logs(self, limit: int = 100) -> list[OperationLogRecord]:
        """Fetch most recent operation logs across all users, newest first."""
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute(
                "SELECT id, user_id, phone_number, action, details, status, timestamp "
                "FROM operation_history ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [OperationLogRecord.from_row(r) for r in rows]


OperationHistoryRepository = OperationLogRepository


class MetadataRepository:
    """
    Key-value store repository backed by SQLite metadata table.
    """

    def __init__(self, db: Union[DatabaseConnection, aiosqlite.Connection]) -> None:
        self.db = db

    async def get(self, key: str) -> Optional[str]:
        """Get value for a key from metadata table."""
        async with _resolve_conn(self.db) as conn:
            cursor = await conn.execute("SELECT value FROM metadata WHERE key = ?", (str(key),))
            row = await cursor.fetchone()
            if row is not None:
                return str(row["value"])
            return None

    async def set(self, key: str, value: str) -> None:
        """Insert or update a key-value pair in metadata table."""
        now_str = datetime.now(timezone.utc).isoformat()
        async with _resolve_conn(self.db) as conn:
            await conn.execute(
                """
                INSERT INTO metadata (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (str(key), str(value), now_str),
            )
            await conn.commit()
