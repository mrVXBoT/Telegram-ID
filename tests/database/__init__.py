"""
tests.database
==============
Automated tests for asynchronous SQLite database layer:
- test_connection: Connection management, WAL mode, foreign keys, table creation
- test_crud: User, account, unique constraints, cascade deletion, operation logs
- test_migration: JSON migration, idempotency, timestamp preservation, backup creation, missing session detection
"""
