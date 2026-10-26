"""
services
========
Telethon asynchronous MTProto client services for Telegram Account Manager:
- TelethonSessionManager: Client connection pooling, concurrency locking, and safe lifecycle management.
- AuthService: User authentication, phone code requests, 2FA challenge resolution, and error mapping.
- ContactService: Contact extraction with digit filtering, mutual contact queries, and batched contact deletion.
- ChatService: User-created chat and dialog inspection, migration deduplication, and auth code extraction.
"""

from __future__ import annotations

from services.auth_service import (
    AuthService,
    AuthServiceError,
    FloodWaitAuthError,
    Invalid2FAPassword,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberBanned,
    PhoneNumberInvalid,
    SignInResult,
)
from services.chat_service import ChatInfo, ChatService
from services.contact_service import ContactInfo, ContactService, DeleteResult
from services.session_manager import TelethonSessionManager

__all__ = [
    "TelethonSessionManager",
    "AuthService",
    "SignInResult",
    "AuthServiceError",
    "PhoneNumberInvalid",
    "PhoneNumberBanned",
    "FloodWaitAuthError",
    "PhoneCodeInvalid",
    "PhoneCodeExpired",
    "Invalid2FAPassword",
    "ContactService",
    "ContactInfo",
    "DeleteResult",
    "ChatService",
    "ChatInfo",
]
