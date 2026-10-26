"""
services.contact_service
========================
Contact management, extraction, and batch deletion service for Telegram accounts.

Provides:
- extract_contacts_by_length: Filters contacts by digit length (7, 8, 9, 10, 11, or 7to9).
- get_mutual_contacts: Extracts contacts marked as mutual contacts.
- get_contacts_summary: Computes total, mutual, and digit length statistics.
- delete_all_contacts: Batch deletes contacts in chunks of 100 with rate limiting and progress callback.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Union

from telethon.tl.functions.contacts import DeleteContactsRequest, GetContactsRequest

from services.session_manager import TelethonSessionManager
from utils.filters import count_contacts_by_length, filter_contacts_by_digit_length
from utils.vcf import ContactInfo

logger = logging.getLogger(__name__)


@dataclass
class DeleteResult:
    """
    Summary outcome of a contact deletion operation.

    Attributes:
        total: Total number of contacts targeted for deletion.
        deleted: Number of contacts successfully deleted.
        failed: Number of contacts that failed to delete.
        status: Operation status ('success', 'partial', 'failed').
        error_message: Optional error description if failure occurred.
    """

    total: int
    deleted: int
    failed: int
    status: str = "success"
    error_message: Optional[str] = None

    @property
    def total_contacts(self) -> int:
        """Alias for total to match legacy TG-ID.py naming."""
        return self.total

    @property
    def success_count(self) -> int:
        """Alias for deleted to match legacy TG-ID.py naming."""
        return self.deleted

    @property
    def failed_count(self) -> int:
        """Alias for failed to match legacy TG-ID.py naming."""
        return self.failed


class ContactService:
    """
    Service responsible for contact extraction, digit filtering, and deletion.
    """

    def __init__(self, session_manager: TelethonSessionManager) -> None:
        """
        Initialize ContactService with a TelethonSessionManager.

        Args:
            session_manager: Active session manager instance.
        """
        self.session_manager = session_manager

    async def get_all_contacts(self, phone: str) -> list[ContactInfo]:
        """
        Fetch all contacts for the specified phone number and convert to ContactInfo models.

        Args:
            phone: Account phone number.

        Returns:
            List of ContactInfo objects with user details and mutual contact flags.
        """
        norm_phone = self.session_manager.normalize_phone(phone)
        client = await self.session_manager.get_client(norm_phone, connect=True)

        logger.debug("Fetching contacts for %s via GetContactsRequest", norm_phone)
        contacts_result = await client(GetContactsRequest(hash=0))

        # Build mutual map from contacts list
        raw_contacts = getattr(contacts_result, "contacts", []) or []
        mutual_ids = {
            c.user_id for c in raw_contacts if getattr(c, "mutual", False)
        }

        # Build ContactInfo objects from users list
        raw_users = getattr(contacts_result, "users", []) or []

        # If contacts_result is a list or duck-typed iterable directly (e.g. in test mocks)
        if not raw_users and isinstance(contacts_result, list):
            raw_users = contacts_result

        contact_infos: list[ContactInfo] = []
        for user in raw_users:
            if isinstance(user, ContactInfo):
                contact_infos.append(user)
                continue

            uid = getattr(user, "id", None)
            if uid is None and isinstance(user, dict):
                uid = user.get("id", user.get("user_id"))

            if uid is None:
                continue

            user_phone = getattr(user, "phone", None)
            if user_phone is None and isinstance(user, dict):
                user_phone = user.get("phone")

            first_name = getattr(user, "first_name", None)
            if first_name is None and isinstance(user, dict):
                first_name = user.get("first_name")

            last_name = getattr(user, "last_name", None)
            if last_name is None and isinstance(user, dict):
                last_name = user.get("last_name")

            is_mut = (
                uid in mutual_ids
                or bool(getattr(user, "mutual_contact", False))
                or (isinstance(user, dict) and bool(user.get("is_mutual", False)))
            )

            contact_infos.append(
                ContactInfo(
                    id=uid,
                    phone=user_phone,
                    first_name=first_name,
                    last_name=last_name,
                    is_mutual=is_mut,
                )
            )

        logger.info("Retrieved %d contacts for account %s", len(contact_infos), norm_phone)
        return contact_infos

    async def extract_contacts_by_length(
        self, phone: str, id_length: Union[int, str]
    ) -> list[ContactInfo]:
        """
        Extract contacts whose Telegram User ID matches the specified digit length or range.

        Args:
            phone: Account phone number.
            id_length: Single length (7, 8, 9, 10, 11) or range ('7to9').

        Returns:
            List of matching ContactInfo instances.
        """
        all_contacts = await self.get_all_contacts(phone)
        filtered = filter_contacts_by_digit_length(all_contacts, id_length)
        logger.info(
            "Filtered %d/%d contacts with length %s for %s",
            len(filtered),
            len(all_contacts),
            id_length,
            phone,
        )
        return filtered

    async def get_mutual_contacts(self, phone: str) -> list[ContactInfo]:
        """
        Extract contacts where mutual contact is True (both parties saved each other).

        Args:
            phone: Account phone number.

        Returns:
            List of mutual ContactInfo instances.
        """
        all_contacts = await self.get_all_contacts(phone)
        mutual_contacts = [c for c in all_contacts if c.is_mutual]
        logger.info(
            "Found %d mutual contacts out of %d for %s",
            len(mutual_contacts),
            len(all_contacts),
            phone,
        )
        return mutual_contacts

    async def get_contacts_summary(self, phone: str) -> dict[str, Any]:
        """
        Compute total, mutual, and digit-length breakdown for an account's contacts.

        Args:
            phone: Account phone number.

        Returns:
            Dictionary with counts: total, mutual, breakdown {7: N, 8: N, ...}, top_samples.
        """
        all_contacts = await self.get_all_contacts(phone)
        breakdown = count_contacts_by_length(all_contacts, [7, 8, 9, 10, 11])
        mutual_count = sum(1 for c in all_contacts if c.is_mutual)

        return {
            "total": len(all_contacts),
            "mutual": mutual_count,
            "breakdown": breakdown,
            "samples": all_contacts[:5],
        }

    async def delete_all_contacts(
        self,
        phone: str,
        progress_callback: Optional[
            Union[
                Callable[[int, int], Awaitable[None]],
                Callable[[int, int], None],
            ]
        ] = None,
        batch_delay: float = 1.0,
    ) -> DeleteResult:
        """
        Delete all contacts from the Telegram account in batches of 100.

        Matches MTProto DeleteContactsRequest specifications with 1-second pauses
        and progress callbacks.

        Args:
            phone: Account phone number.
            progress_callback: Optional callback(deleted_count, total_count) for UI progress updates.
            batch_delay: Seconds to wait between batches (default: 1.0, set to 0.0 for fast tests).

        Returns:
            DeleteResult with counts of deleted, failed, and total contacts.
        """
        norm_phone = self.session_manager.normalize_phone(phone)
        client = await self.session_manager.get_client(norm_phone, connect=True)

        contacts_result = await client(GetContactsRequest(hash=0))

        # Collect user identifiers
        raw_contacts = getattr(contacts_result, "contacts", None)
        if raw_contacts:
            target_ids = [c.user_id for c in raw_contacts if hasattr(c, "user_id")]
        else:
            raw_users = getattr(contacts_result, "users", None) or []
            target_ids = [u.id for u in raw_users if hasattr(u, "id")]

        total = len(target_ids)
        if total == 0:
            logger.info("No contacts to delete for %s", norm_phone)
            return DeleteResult(total=0, deleted=0, failed=0, status="success")

        logger.info("Deleting %d contacts for %s in batches of 100", total, norm_phone)
        batch_size = 100
        deleted_count = 0
        failed_count = 0

        for i in range(0, total, batch_size):
            chunk = target_ids[i : i + batch_size]
            try:
                await client(DeleteContactsRequest(id=chunk))
                deleted_count += len(chunk)
                logger.debug("Deleted batch of %d contacts for %s", len(chunk), norm_phone)
            except Exception as e:
                logger.error("Failed to delete batch for %s: %s", norm_phone, e)
                failed_count += len(chunk)

            if progress_callback is not None:
                try:
                    res = progress_callback(deleted_count, total)
                    if inspect.isawaitable(res):
                        await res
                except Exception as cb_err:
                    logger.warning("Error in delete_all_contacts progress callback: %s", cb_err)

            if (i + batch_size < total) and batch_delay > 0:
                await asyncio.sleep(batch_delay)

        status = "success" if failed_count == 0 else ("partial" if deleted_count > 0 else "failed")
        return DeleteResult(
            total=total,
            deleted=deleted_count,
            failed=failed_count,
            status=status,
        )
