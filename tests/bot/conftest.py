"""
tests.bot.conftest
==================
Pytest fixtures for bot test suite, ensuring clean async teardown of database connections.
"""

from __future__ import annotations

import pytest
from database.connection import DatabaseConnection


@pytest.fixture
async def db():
    """Async fixture providing an initialized in-memory database with clean teardown."""
    conn_mgr = DatabaseConnection(":memory:")
    await conn_mgr.init_db()
    try:
        yield conn_mgr
    finally:
        await conn_mgr.close()


@pytest.fixture
async def db_conn(db: DatabaseConnection):
    """Alias for db fixture for compatibility."""
    return db
