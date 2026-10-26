"""
services.session_manager
========================
Telethon client lifecycle manager with connection pooling, per-phone concurrency locks,
and leak-free session cleanup for Windows compatibility.

Key Capabilities:
- Client Connection Pooling: Reuses connected TelegramClient instances across requests.
- Per-Phone Lock Synchronization: Serializes MTProto RPC calls per phone to prevent state corruption.
- Lazy Event Loop Binding: Client instances are instantiated inside active coroutines on the running loop.
- Safe Windows File Disconnect: Always calls client.disconnect() and closes SQLite session handles
  prior to file unlinking, preventing WinError 32 (PermissionError).
- Graceful Shutdown: disconnect_all() cleanly terminates all active client connections.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Any, Optional, Union

from telethon import TelegramClient

from config.settings import Settings, get_settings
from utils.phone import sanitize_phone_number

logger = logging.getLogger(__name__)


class TelethonSessionManager:
    """
    Asynchronous connection manager and session pool for Telethon MTProto clients.

    Thread and coroutine safe: manages individual asyncio.Lock per phone number.
    Ensures existing session files in the sessions directory remain compatible.
    """

    def __init__(
        self,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        sessions_dir: Optional[Union[str, Path]] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        """
        Initialize the session manager.

        Args:
            api_id: Optional Telegram API ID. Falls back to settings.
            api_hash: Optional Telegram API Hash. Falls back to settings.
            sessions_dir: Optional sessions directory path. Falls back to settings.
            settings: Optional explicit Settings instance.
        """
        if settings is not None:
            self.api_id = api_id if api_id is not None else settings.api_id
            self.api_hash = api_hash if api_hash is not None else settings.api_hash
            self.sessions_dir = (
                Path(sessions_dir) if sessions_dir is not None else settings.sessions_dir
            )
        elif api_id is not None and api_hash is not None:
            self.api_id = api_id
            self.api_hash = api_hash
            self.sessions_dir = Path(sessions_dir) if sessions_dir is not None else Path("sessions")
        else:
            cfg = get_settings()
            self.api_id = api_id if api_id is not None else cfg.api_id
            self.api_hash = api_hash if api_hash is not None else cfg.api_hash
            self.sessions_dir = (
                Path(sessions_dir) if sessions_dir is not None else cfg.sessions_dir
            )

        # Ensure directory exists on disk
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        self._clients: dict[str, TelegramClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock: asyncio.Lock = asyncio.Lock()

    def normalize_phone(self, phone: str) -> str:
        """
        Normalize and sanitize a phone number string.

        Args:
            phone: Raw phone number string.

        Returns:
            Normalized international phone string (e.g. '+15156723850').
        """
        sanitized = sanitize_phone_number(phone)
        if not sanitized.startswith("+"):
            return f"+{sanitized}"
        return sanitized

    _normalize_phone = normalize_phone

    def get_session_base_path(self, phone: str) -> Path:
        """
        Get base path (without extension) for Telethon SQLite session.

        Telethon automatically appends '.session' to this path.
        """
        norm_phone = self.normalize_phone(phone)
        return self.sessions_dir / norm_phone

    def get_session_file_path(self, phone: str) -> Path:
        """Get the actual .session file path on disk."""
        norm_phone = self.normalize_phone(phone)
        return self.sessions_dir / f"{norm_phone}.session"

    def session_exists(self, phone: str) -> bool:
        """Check whether a .session file exists on disk for the given phone."""
        return self.get_session_file_path(phone).is_file()

    def has_client(self, phone: str) -> bool:
        """Check whether an active client is cached in the pool for this phone."""
        norm_phone = self.normalize_phone(phone)
        return norm_phone in self._clients

    def get_lock(self, phone: str) -> asyncio.Lock:
        """
        Retrieve or create an asyncio.Lock for the specified phone number.

        Args:
            phone: Target phone number.

        Returns:
            asyncio.Lock dedicated to serializing operations on this phone.
        """
        norm_phone = self.normalize_phone(phone)
        if norm_phone not in self._locks:
            self._locks[norm_phone] = asyncio.Lock()
        return self._locks[norm_phone]

    async def _close_client(self, client: TelegramClient, phone: str) -> None:
        """
        Safely disconnect a client and release its SQLite session handle.

        Closes MTProto network connections and releases the SQLite file descriptor,
        preventing WinError 32 during subsequent file manipulations on Windows.
        """
        try:
            await client.disconnect()
        except Exception as e:
            logger.warning("Error disconnecting client for %s: %s", phone, e)
        finally:
            if hasattr(client, "session") and hasattr(client.session, "close"):
                try:
                    close_res = client.session.close()
                    if inspect.isawaitable(close_res):
                        await close_res
                except Exception:
                    pass

    async def get_client(
        self, phone: str, connect: bool = True
    ) -> TelegramClient:
        """
        Retrieve a pooled TelegramClient for the phone, creating and connecting if needed.

        Args:
            phone: Target phone number in international format.
            connect: If True, ensures the client is connected before returning.

        Returns:
            TelegramClient instance bound to the active event loop.
        """
        norm_phone = self.normalize_phone(phone)
        lock = self.get_lock(norm_phone)

        async with lock:
            if norm_phone in self._clients:
                client = self._clients[norm_phone]
                if connect and not client.is_connected():
                    logger.debug("Reconnecting existing client for %s", norm_phone)
                    try:
                        await client.connect()
                    except Exception:
                        await self._close_client(client, norm_phone)
                        self._clients.pop(norm_phone, None)
                        raise
                return client

            session_base = self.get_session_base_path(norm_phone)
            logger.debug(
                "Instantiating new TelegramClient for %s at %s",
                norm_phone,
                session_base,
            )
            client = TelegramClient(
                str(session_base), self.api_id, self.api_hash
            )

            if connect:
                try:
                    await client.connect()
                except Exception:
                    await self._close_client(client, norm_phone)
                    raise

            self._clients[norm_phone] = client
            return client

    async def is_authorized(self, phone: str) -> bool:
        """
        Check whether the client for the specified phone is currently authorized.

        Args:
            phone: Target phone number.

        Returns:
            True if user is authenticated with Telegram, False otherwise.
        """
        client = await self.get_client(phone, connect=True)
        return await client.is_user_authorized()

    async def disconnect(self, phone: str) -> None:
        """
        Safely disconnect and release the client for the specified phone.

        Closes MTProto network connections and releases the SQLite session handle,
        avoiding WinError 32 during subsequent file manipulations.

        Args:
            phone: Phone number to disconnect.
        """
        norm_phone = self.normalize_phone(phone)
        lock = self.get_lock(norm_phone)

        async with lock:
            client = self._clients.pop(norm_phone, None)
            if client is not None:
                await self._close_client(client, norm_phone)

    async def disconnect_all(self) -> None:
        """
        Gracefully disconnect all active clients in the pool.

        Used during application shutdown or test cleanup.
        Drains the pool iteratively so any client added concurrently is also safely disconnected.
        """
        async with self._global_lock:
            while self._clients:
                phone, client = self._clients.popitem()
                await self._close_client(client, phone)

    async def remove_session_file(self, phone: str) -> bool:
        """
        Safely remove the .session file from disk, ensuring the client is disconnected first
        under atomic per-phone lock acquisition.

        This ordering and atomicity is mandatory on Windows to avoid:
        PermissionError: [WinError 32] The process cannot access the file because it is being used by another process.

        Args:
            phone: Target phone number.

        Returns:
            True if file existed and was removed, False if file did not exist.
        """
        norm_phone = self.normalize_phone(phone)
        lock = self.get_lock(norm_phone)

        async with lock:
            client = self._clients.pop(norm_phone, None)
            if client is not None:
                await self._close_client(client, norm_phone)

            session_file = self.get_session_file_path(norm_phone)
            if session_file.is_file():
                try:
                    session_file.unlink()
                    logger.info("Successfully removed session file %s", session_file)
                    return True
                except PermissionError as e:
                    logger.error("Failed to remove session file %s due to file lock: %s", session_file, e)
                    raise
            return False

    def get_active_phones(self) -> list[str]:
        """Return list of phone numbers currently cached in the pool."""
        return list(self._clients.keys())

    async def __aenter__(self) -> TelethonSessionManager:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Any,
    ) -> None:
        await self.disconnect_all()
