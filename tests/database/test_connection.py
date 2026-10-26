"""
tests.database.test_connection
==============================
Tests for asynchronous SQLite connection management:
- In-memory (:memory:) connection behavior
- File-based connection and WAL journal mode
- Foreign key pragma enforcement
- Schema initialization (tables and indexes)
- Context manager protocol
- Auto-creation of parent directories
- Row factory column-name indexing
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import pytest

from database.connection import DatabaseConnection


@pytest.mark.database
async def test_in_memory_connection_pragmas():
    """Verify that in-memory database enables foreign keys and operates as expected."""
    db = DatabaseConnection(":memory:")
    assert db.is_memory is True
    assert db.path == ":memory:"

    async with db.get_db() as conn:
        cursor = await conn.execute("PRAGMA foreign_keys;")
        row = await cursor.fetchone()
        assert row[0] == 1  # Foreign keys enabled

        cursor = await conn.execute("PRAGMA journal_mode;")
        row = await cursor.fetchone()
        assert row[0].lower() == "memory"

    await db.close()


@pytest.mark.database
async def test_file_based_wal_mode(tmp_path: Path):
    """Verify that file-backed database executes WAL journal mode successfully."""
    db_file = tmp_path / "test_wal.db"
    db = DatabaseConnection(db_file)
    assert db.is_memory is False

    async with db.get_db() as conn:
        cursor = await conn.execute("PRAGMA journal_mode;")
        row = await cursor.fetchone()
        assert row[0].lower() == "wal"

        cursor = await conn.execute("PRAGMA foreign_keys;")
        row = await cursor.fetchone()
        assert row[0] == 1


@pytest.mark.database
async def test_table_and_index_creation_init_db(tmp_path: Path):
    """Verify that init_db creates all required tables and indexes."""
    db_file = tmp_path / "test_init.db"
    db = DatabaseConnection(db_file)
    await db.init_db()

    async with db.get_db() as conn:
        cursor = await conn.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'index')")
        items = await cursor.fetchall()
        item_names = {row["name"] for row in items}

        # Check required tables
        assert "users" in item_names
        assert "accounts" in item_names
        assert "operation_history" in item_names
        assert "metadata" in item_names

        # Check required indexes
        assert "idx_accounts_user_id" in item_names
        assert "idx_accounts_phone" in item_names
        assert "idx_history_user_id" in item_names
        assert "idx_history_timestamp" in item_names


@pytest.mark.database
async def test_row_factory_aiosqlite_row(tmp_path: Path):
    """Verify that connections use aiosqlite.Row for column-name lookups."""
    db = DatabaseConnection(":memory:")
    await db.init_db()

    async with db.get_db() as conn:
        await conn.execute("INSERT INTO metadata (key, value, updated_at) VALUES (?, ?, ?)", ("foo", "bar", "2026-01-01"))
        await conn.commit()

        cursor = await conn.execute("SELECT key, value FROM metadata WHERE key = ?", ("foo",))
        row = await cursor.fetchone()
        assert row is not None
        assert row["key"] == "foo"
        assert row["value"] == "bar"

    await db.close()


@pytest.mark.database
async def test_persistent_connect_and_close(tmp_path: Path):
    """Verify connect() returns open connection and close() cleans it up."""
    db_file = tmp_path / "test_persist.db"
    db = DatabaseConnection(db_file)

    conn1 = await db.connect()
    assert conn1 is not None

    # Repeated connect returns same connection
    conn2 = await db.connect()
    assert conn1 is conn2

    await db.close()
    assert db._shared_conn is None


@pytest.mark.database
async def test_auto_create_parent_directory(tmp_path: Path):
    """Verify connecting to a database in non-existent nested directory creates parent dirs."""
    nested_dir = tmp_path / "deep" / "nested" / "dir"
    assert not nested_dir.exists()
    db_file = nested_dir / "nested_bot.db"

    db = DatabaseConnection(db_file)
    async with db.get_db() as conn:
        await conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
        await conn.commit()

    assert nested_dir.exists()
    assert db_file.exists()


@pytest.mark.database
async def test_context_manager_protocol(tmp_path: Path):
    """Verify DatabaseConnection can be entered directly using 'async with'."""
    db_file = tmp_path / "test_ctx.db"
    async with DatabaseConnection(db_file) as conn:
        cursor = await conn.execute("SELECT 1 AS val")
        row = await cursor.fetchone()
        assert row["val"] == 1
