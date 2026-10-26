"""
services.auth_service
=====================
Telethon authentication lifecycle service handling code requests, sign-in,
2FA password challenges, and exception mapping.

Provides:
- send_code: Requests Telegram SMS/app verification code and captures phone_code_hash.
- sign_in: Signs into Telegram with verification code or 2FA password.
- Exception Mapping: Maps Telethon MTProto errors to domain result statuses and custom exceptions.
- log_out: Gracefully terminates the Telegram MTProto session and removes local files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from services.session_manager import TelethonSessionManager

logger = logging.getLogger(__name__)


class AuthServiceError(Exception):
    """Base exception for authentication service errors."""


class PhoneNumberInvalid(AuthServiceError):
    """Raised when the submitted phone number is rejected by Telegram."""


class PhoneNumberBanned(AuthServiceError):
    """Raised when the phone number is banned from Telegram."""


class FloodWaitAuthError(AuthServiceError):
    """Raised when Telegram imposes a rate limit / flood wait on auth requests."""

    def __init__(self, seconds: int, message: Optional[str] = None) -> None:
        self.seconds = seconds
        msg = message or f"Flood wait: please wait {seconds} seconds before retrying."
        super().__init__(msg)


class PhoneCodeInvalid(AuthServiceError):
    """Raised when the submitted verification code is incorrect."""


class PhoneCodeExpired(AuthServiceError):
    """Raised when the verification code has expired."""


class Invalid2FAPassword(AuthServiceError):
    """Raised when the submitted two-step verification password is incorrect."""


@dataclass
class SignInResult:
    """
    Standardized result for sign-in and 2FA verification attempts.

    Statuses:
    - 'success': Authentication succeeded, session is fully authorized.
    - '2fa_required': Two-step verification password is required.
    - 'invalid_code': Verification code was incorrect.
    - 'expired_code': Verification code has expired.
    - 'banned': Phone number has been banned by Telegram.
    - 'flood_wait': Rate limit imposed by Telegram servers.
    - 'invalid_password': 2FA password was incorrect.
    - 'error': Generic or unexpected authentication failure.
    """

    status: str
    phone: str
    user_id: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    message: Optional[str] = None
    wait_seconds: Optional[int] = None

    @property
    def is_success(self) -> bool:
        """Check if sign in completed successfully."""
        return self.status == "success"

    @property
    def requires_2fa(self) -> bool:
        """Check if 2FA password is required to complete authentication."""
        return self.status == "2fa_required"


class AuthService:
    """
    Authentication manager handling Telethon sign-in flow and 2FA challenges.
    """

    def __init__(self, session_manager: TelethonSessionManager) -> None:
        """
        Initialize AuthService with a TelethonSessionManager.

        Args:
            session_manager: Active session manager instance.
        """
        self.session_manager = session_manager
        # Cache for phone_code_hash keyed by normalized phone
        self._phone_code_hashes: dict[str, str] = {}

    def get_cached_hash(self, phone: str) -> Optional[str]:
        """Retrieve cached phone_code_hash for a phone number."""
        norm_phone = self.session_manager.normalize_phone(phone)
        return self._phone_code_hashes.get(norm_phone)

    def set_cached_hash(self, phone: str, phone_code_hash: str) -> None:
        """Cache phone_code_hash for a phone number."""
        norm_phone = self.session_manager.normalize_phone(phone)
        self._phone_code_hashes[norm_phone] = phone_code_hash

    def clear_cached_hash(self, phone: str) -> None:
        """Remove cached phone_code_hash for a phone number."""
        norm_phone = self.session_manager.normalize_phone(phone)
        self._phone_code_hashes.pop(norm_phone, None)

    async def send_code(self, phone: str) -> str:
        """
        Request a verification code from Telegram for the specified phone.

        Args:
            phone: Phone number in international format.

        Returns:
            phone_code_hash string required for subsequent sign_in call.

        Raises:
            PhoneNumberInvalid: If phone number is invalid.
            PhoneNumberBanned: If phone number is banned.
            FloodWaitAuthError: If Telegram requires waiting.
            AuthServiceError: For other MTProto errors.
        """
        norm_phone = self.session_manager.normalize_phone(phone)
        client = await self.session_manager.get_client(norm_phone, connect=True)

        try:
            logger.info("Requesting verification code for %s", norm_phone)
            sent_code = await client.send_code_request(norm_phone)

            phone_code_hash: Optional[str] = None
            if hasattr(sent_code, "phone_code_hash"):
                phone_code_hash = str(sent_code.phone_code_hash)
            elif isinstance(sent_code, dict):
                phone_code_hash = str(sent_code.get("phone_code_hash", ""))

            if not phone_code_hash:
                raise AuthServiceError("Telethon did not return a valid phone_code_hash")

            self.set_cached_hash(norm_phone, phone_code_hash)
            return phone_code_hash

        except PhoneNumberInvalidError as e:
            logger.warning("Phone number %s is invalid: %s", norm_phone, e)
            raise PhoneNumberInvalid(f"Phone number {norm_phone} is invalid.") from e
        except PhoneNumberBannedError as e:
            logger.error("Phone number %s is banned: %s", norm_phone, e)
            raise PhoneNumberBanned(f"Phone number {norm_phone} is banned.") from e
        except FloodWaitError as e:
            logger.warning("Flood wait on send_code for %s: %s seconds", norm_phone, e.seconds)
            raise FloodWaitAuthError(
                seconds=e.seconds,
                message=f"Too many attempts. Please wait {e.seconds} seconds.",
            ) from e
        except Exception as e:
            logger.error("Unexpected error in send_code for %s: %s", norm_phone, e)
            raise AuthServiceError(f"Failed to send code: {e}") from e

    async def sign_in(
        self,
        phone: str,
        code: Optional[str] = None,
        phone_code_hash: Optional[str] = None,
        password: Optional[str] = None,
    ) -> SignInResult:
        """
        Sign into Telegram using verification code or 2FA password.

        Args:
            phone: Phone number in international format.
            code: Optional verification code string.
            phone_code_hash: Optional phone_code_hash returned by send_code.
            password: Optional 2FA password string.

        Returns:
            SignInResult with status ('success', '2fa_required', 'invalid_code', etc.)
        """
        norm_phone = self.session_manager.normalize_phone(phone)
        client = await self.session_manager.get_client(norm_phone, connect=True)

        resolved_hash = phone_code_hash or self.get_cached_hash(norm_phone)

        try:
            if password is not None and not code:
                # 2FA password step
                logger.info("Verifying 2FA password for %s", norm_phone)
                await client.sign_in(password=password)
            else:
                # Standard verification code step
                clean_code = str(code).strip().replace(" ", "").replace("-", "") if code else ""
                logger.info("Signing in with code for %s", norm_phone)
                await client.sign_in(
                    phone=norm_phone,
                    code=clean_code,
                    phone_code_hash=resolved_hash,
                )

            # Retrieve authenticated user info
            me = await client.get_me()
            user_id = getattr(me, "id", None)
            first_name = getattr(me, "first_name", None)
            last_name = getattr(me, "last_name", None)
            username = getattr(me, "username", None)

            # Clean up cached hash on successful sign-in
            self.clear_cached_hash(norm_phone)

            logger.info("Successfully signed in user %s for %s", user_id, norm_phone)
            return SignInResult(
                status="success",
                phone=norm_phone,
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                username=username,
                message="Successfully signed in.",
            )

        except SessionPasswordNeededError:
            logger.info("2FA password required for %s", norm_phone)
            return SignInResult(
                status="2fa_required",
                phone=norm_phone,
                message="Two-step verification password is required.",
            )

        except PhoneCodeInvalidError:
            logger.warning("Invalid code provided for %s", norm_phone)
            return SignInResult(
                status="invalid_code",
                phone=norm_phone,
                message="Invalid verification code. Please check and try again.",
            )

        except PhoneCodeExpiredError:
            logger.warning("Code expired for %s", norm_phone)
            return SignInResult(
                status="expired_code",
                phone=norm_phone,
                message="Verification code has expired. Please request a new code.",
            )

        except PhoneNumberBannedError:
            logger.error("Phone number %s is banned during sign-in", norm_phone)
            return SignInResult(
                status="banned",
                phone=norm_phone,
                message="This phone number has been banned by Telegram.",
            )

        except FloodWaitError as e:
            logger.warning("Flood wait on sign_in for %s: %s seconds", norm_phone, e.seconds)
            return SignInResult(
                status="flood_wait",
                phone=norm_phone,
                wait_seconds=e.seconds,
                message=f"Too many attempts. Please wait {e.seconds} seconds.",
            )

        except PasswordHashInvalidError:
            logger.warning("Invalid 2FA password for %s", norm_phone)
            return SignInResult(
                status="invalid_password",
                phone=norm_phone,
                message="Invalid 2FA password. Please try again.",
            )

        except Exception as e:
            logger.error("Unexpected error during sign_in for %s: %s", norm_phone, e)
            return SignInResult(
                status="error",
                phone=norm_phone,
                message=f"Authentication error: {e}",
            )

    async def sign_in_2fa(self, phone: str, password: str) -> SignInResult:
        """
        Verify two-step verification (2FA) password.

        Args:
            phone: Phone number.
            password: User's 2FA password.

        Returns:
            SignInResult indicating success or failure.
        """
        return await self.sign_in(phone=phone, password=password)

    async def log_out(self, phone: str) -> bool:
        """
        Log out the account from Telegram and delete its local session file.

        Disconnects client first to avoid Windows file locking errors.

        Args:
            phone: Target phone number.

        Returns:
            True if logout and deletion succeeded.
        """
        norm_phone = self.session_manager.normalize_phone(phone)
        client = await self.session_manager.get_client(norm_phone, connect=True)

        try:
            if await client.is_user_authorized():
                logger.info("Logging out account %s from Telegram", norm_phone)
                await client.log_out()
        except Exception as e:
            logger.warning("Error during Telegram client.log_out() for %s: %s", norm_phone, e)

        self.clear_cached_hash(norm_phone)
        # Safely disconnect and remove the .session file
        await self.session_manager.remove_session_file(norm_phone)
        return True
