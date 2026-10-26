"""
database.connection
===================
Asynchronous SQLite connection manager using aiosqlite.

Features:
- Automatic execution of PRAGMA journal_mode = WAL and PRAGMA foreign_keys = ON.
- First-class support for both file-backed databases and ':memory:' databases.
- Async context manager access via get_db().
- Parent directory creation for file paths.
- Connection pooling / persistent handle reuse for in-memory and managed contexts.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional, Union

import aiosqlite


class DatabaseConnection:
    """
    Manages asynchronous SQLite connections via aiosqlite.

    Enforces foreign keys, enables WAL journal mode, and provides
    context-managed access to active connections.

    Usage:
        db = DatabaseConnection("data/bot.db")
        async with db.get_db() as conn:
            await conn.execute(...)

        # Or directly as context manager:
        async with DatabaseConnection(":memory:") as conn:
            await conn.execute(...)
    """

    def __init__(self, database_path: Union[str, Path, None] = None) -> None:
        """
        Initialize DatabaseConnection.

        Args:
            database_path: Filesystem path to SQLite file or ':memory:'.
                           Defaults to Settings.database_path if None.
        """
        if database_path is None:
            try:
                from config.settings import get_settings

                self.database_path: Union[str, Path] = get_settings().database_path
            except Exception:
                self.database_path = Path("data/bot.db")
        else:
            self.database_path = database_path

        self._path_str = str(self.database_path)
        self._is_memory = self._path_str == ":memory:" or "mode=memory" in self._path_str
        self._shared_conn: Optional[aiosqlite.Connection] = None
        self._lock_obj: Optional[asyncio.Lock] = None

    @property
    def _lock(self) -> asyncio.Lock:
        """Lazily initialize asyncio.Lock on the current event loop."""
        if self._lock_obj is None:
            self._lock_obj = asyncio.Lock()
        return self._lock_obj

    @property
    def path(self) -> str:
        """Return the database path as a string."""
        return self._path_str

    @property
    def is_memory(self) -> bool:
        """Return True if connection targets an in-memory database."""
        return self._is_memory

    async def _configure_connection(self, conn: aiosqlite.Connection) -> None:
        """
        Configure connection pragmas and row factory.
        Enforces foreign key constraints and WAL journal mode.
        """
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON;")
        # Note: on :memory: DBs, SQLite retains journal_mode='memory'
        await conn.execute("PRAGMA journal_mode = WAL;")

    async def connect(self) -> aiosqlite.Connection:
        """
        Open, configure, and store a persistent connection.
        If already connected, returns existing connection.
        """
        async with self._lock:
            if self._shared_conn is None:
                if not self._is_memory:
                    p = Path(self.database_path)
                    if p.parent != Path(".") and not p.parent.exists():
                        p.parent.mkdir(parents=True, exist_ok=True)

                conn_proxy = aiosqlite.connect(self._path_str)
                conn_proxy.daemon = True
                conn = await conn_proxy
                await self._configure_connection(conn)
                self._shared_conn = conn
            return self._shared_conn

    async def close(self) -> None:
        """Close the persistent shared connection if open."""
        async with self._lock:
            if self._shared_conn is not None:
                await self._shared_conn.close()
                self._shared_conn = None
                await asyncio.sleep(0.01)

    @asynccontextmanager
    async def get_db(self) -> AsyncIterator[aiosqlite.Connection]:
        """
        Async context manager yielding an active aiosqlite.Connection.

        For in-memory databases (:memory:), the connection is retained across
        calls so schema and data persist. For file-based databases without an
        explicitly opened persistent connection, each context manager call opens
        and closes its own connection cleanly.
        """
        if self._is_memory:
            # Memory databases need a persistent connection so tables aren't lost
            conn = await self.connect()
            yield conn
        elif self._shared_conn is not None:
            yield self._shared_conn
        else:
            p = Path(self.database_path)
            if p.parent != Path(".") and not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)

            conn_proxy = aiosqlite.connect(self._path_str)
            conn_proxy.daemon = True
            async with conn_proxy as conn:
                await self._configure_connection(conn)
                yield conn

    async def init_db(self) -> None:
        """
        Initialize all tables and indexes in the database.
        Delegates to repository.init_db.
        """
        from database.repository import init_db

        async with self.get_db() as conn:
            await init_db(conn)

    async def __aenter__(self) -> aiosqlite.Connection:
        """Enter context manager, connecting and returning connection."""
        return await self.connect()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager, closing connection."""
        await self.close()
