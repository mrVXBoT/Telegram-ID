"""
database.models
===============
Data models and representations for database entities:
- UserRecord: Registered Telegram bot user
- AccountRecord: Linked Telegram client account with session status
- OperationLogRecord: Audit record for operations and actions
- MigrationResult: Summary of JSON-to-SQLite migration execution
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional


@dataclass
class UserRecord:
    """
    Representation of a Telegram bot user.

    Attributes:
        user_id: 64-bit Telegram user ID.
        created_at: ISO 8601 UTC timestamp of account creation.
        last_seen_at: ISO 8601 UTC timestamp of user's last interaction.
        is_active: Whether the user is currently active.
    """

    user_id: int
    created_at: str
    last_seen_at: str
    is_active: bool = True

    @property
    def telegram_id(self) -> int:
        """Alias for user_id to match Telegram Bot API conventions."""
        return self.user_id

    def to_dict(self) -> dict[str, Any]:
        """Convert record to dictionary."""
        return asdict(self)

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | tuple[Any, ...]) -> UserRecord:
        """Construct UserRecord from database row or mapping."""
        if hasattr(row, "keys"):
            return cls(
                user_id=int(row["user_id"]),
                created_at=str(row["created_at"]),
                last_seen_at=str(row["last_seen_at"]),
                is_active=bool(row["is_active"]),
            )
        # Tuple format: (user_id, created_at, last_seen_at, is_active)
        return cls(
            user_id=int(row[0]),
            created_at=str(row[1]),
            last_seen_at=str(row[2]),
            is_active=bool(row[3]),
        )


@dataclass
class AccountRecord:
    """
    Representation of a linked Telegram account.

    Attributes:
        id: Primary key identifier (None if unsaved).
        user_id: Foreign key referencing the owning bot user.
        phone_number: Normalized international phone number (e.g. +15156723850).
        session_file: Relative filename of the .session file.
        status: Account status: 'active', 'missing_session', 'unauthorized', 'banned'.
        added_at: ISO 8601 UTC timestamp when account was linked.
        last_used_at: ISO 8601 UTC timestamp of last successful operation.
    """

    id: Optional[int]
    user_id: int
    phone_number: str
    session_file: Optional[str] = None
    status: str = "active"
    added_at: str = ""
    last_used_at: Optional[str] = None

    @property
    def phone(self) -> str:
        """Alias for phone_number."""
        return self.phone_number

    def to_dict(self) -> dict[str, Any]:
        """Convert record to dictionary."""
        return asdict(self)

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | tuple[Any, ...]) -> AccountRecord:
        """Construct AccountRecord from database row or mapping."""
        if hasattr(row, "keys"):
            return cls(
                id=int(row["id"]) if row["id"] is not None else None,
                user_id=int(row["user_id"]),
                phone_number=str(row["phone_number"]),
                session_file=str(row["session_file"]) if row["session_file"] is not None else None,
                status=str(row["status"]),
                added_at=str(row["added_at"]),
                last_used_at=str(row["last_used_at"]) if row["last_used_at"] is not None else None,
            )
        # Tuple format: (id, user_id, phone_number, session_file, status, added_at, last_used_at)
        return cls(
            id=int(row[0]) if row[0] is not None else None,
            user_id=int(row[1]),
            phone_number=str(row[2]),
            session_file=str(row[3]) if row[3] is not None else None,
            status=str(row[4]),
            added_at=str(row[5]),
            last_used_at=str(row[6]) if row[6] is not None else None,
        )


@dataclass
class OperationLogRecord:
    """
    Representation of an audit trail log entry.

    Attributes:
        id: Primary key identifier (None if unsaved).
        action: Executed action (e.g. 'auth_add', 'export_vcf', 'delete_contacts').
        status: Operation outcome ('success', 'failure', 'cancelled').
        timestamp: ISO 8601 UTC timestamp of the operation.
        user_id: Optional foreign key to users table.
        phone_number: Optional phone number involved in the operation.
        details: Optional JSON string or descriptive text with execution details.
    """

    id: Optional[int]
    action: str
    status: str
    timestamp: str
    user_id: Optional[int] = None
    phone_number: Optional[str] = None
    details: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert record to dictionary."""
        return asdict(self)

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | tuple[Any, ...]) -> OperationLogRecord:
        """Construct OperationLogRecord from database row or mapping."""
        if hasattr(row, "keys"):
            return cls(
                id=int(row["id"]) if row["id"] is not None else None,
                user_id=int(row["user_id"]) if row["user_id"] is not None else None,
                phone_number=str(row["phone_number"]) if row["phone_number"] is not None else None,
                action=str(row["action"]),
                details=str(row["details"]) if row["details"] is not None else None,
                status=str(row["status"]),
                timestamp=str(row["timestamp"]),
            )
        # Tuple format: (id, user_id, phone_number, action, details, status, timestamp)
        return cls(
            id=int(row[0]) if row[0] is not None else None,
            user_id=int(row[1]) if row[1] is not None else None,
            phone_number=str(row[2]) if row[2] is not None else None,
            action=str(row[3]),
            details=str(row[4]) if row[4] is not None else None,
            status=str(row[5]),
            timestamp=str(row[6]),
        )


@dataclass
class MigrationResult:
    """
    Summary outcome of JSON-to-SQLite database migration.

    Attributes:
        migrated_users: Number of users successfully migrated or merged.
        migrated_accounts: Number of accounts successfully migrated or merged.
        missing_sessions: Number of accounts imported with 'missing_session' status.
        skipped: Whether migration was skipped (e.g. missing file or already migrated).
        details: Human-readable execution notes or error details.
    """

    migrated_users: int = 0
    migrated_accounts: int = 0
    missing_sessions: int = 0
    skipped: bool = False
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
        return asdict(self)
