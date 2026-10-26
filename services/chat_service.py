"""
services.chat_service
=====================
Chat, channel, and dialog inspection service with migration deduplication,
prehistory visibility checking, and Telegram login code extraction.

Provides:
- list_creator_chats: Queries user-created channels, supergroups, and basic groups;
  deduplicates migrated basic chats; probes hidden_prehistory and creation dates.
- get_latest_login_code: Scans peer 777000 (Telegram official notifications) for the
  most recent 5-digit authentication code (pattern: r'\\b\\d{5}\\b').
- get_latest_login_message: Retrieves the complete text of the login notification.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest, GetDialogsRequest
from telethon.tl.types import Channel, Chat, InputPeerEmpty

from services.session_manager import TelethonSessionManager

logger = logging.getLogger(__name__)

# Telegram login code pattern: standalone 5-digit number
LOGIN_CODE_PATTERN = re.compile(r"\b(\d{5})\b")


@dataclass
class ChatInfo:
    """
    Representation of a Telegram chat/channel created and owned by the user.

    Attributes:
        id: Unique Telegram chat/channel ID.
        title: Title / display name of the chat.
        type: Chat classification: 'channel', 'supergroup', or 'group'.
        username: Optional public username (e.g. 'mychannel').
        link: Accessible HTTP link (e.g. 'https://t.me/mychannel' or invite link).
        creator: Whether the user is the creator/owner (True).
        creation_date: Optional formatted date string (YYYY-MM-DD).
        creation_year: Optional integer year of chat creation.
        hidden_prehistory: Optional boolean indicating if chat history is hidden for new members.
        history_visibility: Human-readable status: 'Hidden', 'Visible', or 'Unknown'.
        migrated_from_chat_id: Optional ID of the legacy basic group if migrated to supergroup.
    """

    id: int
    title: str
    type: str
    username: Optional[str] = None
    link: Optional[str] = None
    creator: bool = True
    creation_date: Optional[str] = None
    creation_year: Optional[int] = None
    hidden_prehistory: Optional[bool] = None
    history_visibility: Optional[str] = None
    migrated_from_chat_id: Optional[int] = None

    @property
    def is_channel(self) -> bool:
        """Return True if this is a broadcast channel."""
        return self.type == "channel"

    @property
    def is_supergroup(self) -> bool:
        """Return True if this is a supergroup / megagroup."""
        return self.type == "supergroup"

    @property
    def is_group(self) -> bool:
        """Return True if this is a basic group."""
        return self.type == "group"


class ChatService:
    """
    Service for inspecting dialogs, user-owned chats, and official auth codes.
    """

    def __init__(self, session_manager: TelethonSessionManager) -> None:
        """
        Initialize ChatService with a TelethonSessionManager.

        Args:
            session_manager: Active session manager instance.
        """
        self.session_manager = session_manager

    async def list_creator_chats(self, phone: str) -> list[ChatInfo]:
        """
        Retrieve all channels, supergroups, and groups where the user is the creator.

        Automatically deduplicates basic groups that have been migrated into supergroups
        via `migrated_from_chat_id` and detects history visibility (`hidden_prehistory`).

        Args:
            phone: Account phone number.

        Returns:
            List of ChatInfo objects representing unique user-created chats.
        """
        norm_phone = self.session_manager.normalize_phone(phone)
        client = await self.session_manager.get_client(norm_phone, connect=True)

        logger.info("Fetching dialogs for %s via GetDialogsRequest", norm_phone)
        dialogs = await client(
            GetDialogsRequest(
                offset_date=None,
                offset_id=0,
                offset_peer=InputPeerEmpty(),
                limit=100,
                hash=0,
            )
        )

        all_chats: list[Any] = getattr(dialogs, "chats", []) or []
        # Filter for chats where the user is creator
        creator_chats = [
            chat for chat in all_chats if getattr(chat, "creator", False)
        ]

        # Map to store supergroup full channel responses
        full_channel_cache: dict[int, Any] = {}
        migrated_chat_ids: set[int] = set()

        # Step 1: Detect supergroups and collect migrated_from_chat_id
        for chat in creator_chats:
            is_supergroup = isinstance(chat, Channel) and bool(
                getattr(chat, "megagroup", False)
            )
            if is_supergroup:
                try:
                    full = await client(GetFullChannelRequest(channel=chat))
                    full_channel_cache[chat.id] = full
                    migrated_id = getattr(
                        getattr(full, "full_chat", None),
                        "migrated_from_chat_id",
                        None,
                    )
                    if migrated_id:
                        migrated_chat_ids.add(migrated_id)
                except Exception as e:
                    logger.debug(
                        "Could not fetch full channel info for supergroup %s: %s",
                        chat.id,
                        e,
                    )

        # Step 2: Build ChatInfo objects, filtering out migrated basic groups
        result: list[ChatInfo] = []

        for chat in creator_chats:
            chat_id = getattr(chat, "id", 0)

            # Deduplication: If this basic chat was migrated into an existing supergroup, skip it
            if isinstance(chat, Chat) and chat_id in migrated_chat_ids:
                logger.debug(
                    "Skipping basic chat %s as it migrated to a supergroup",
                    chat_id,
                )
                continue

            # Classify chat type
            if isinstance(chat, Channel) and not getattr(chat, "megagroup", False):
                chat_type = "channel"
            elif isinstance(chat, Channel) and getattr(chat, "megagroup", False):
                chat_type = "supergroup"
            else:
                chat_type = "group"

            # Resolve link
            username = getattr(chat, "username", None)
            link: Optional[str] = None

            if username:
                link = f"https://t.me/{username}"
            else:
                try:
                    invite = await client(ExportChatInviteRequest(peer=chat))
                    link = getattr(invite, "link", None)
                except Exception:
                    clean_id = (
                        str(chat_id)
                        .replace("-100", "")
                        .replace("-", "")
                    )
                    link = f"https://t.me/c/{clean_id}"

            # Check history visibility & migration ID
            hidden_prehistory: Optional[bool] = None
            history_visibility = "Unknown"
            migrated_from_id: Optional[int] = None

            if chat_id in full_channel_cache:
                full = full_channel_cache[chat_id]
                full_chat = getattr(full, "full_chat", None)
                migrated_from_id = getattr(full_chat, "migrated_from_chat_id", None)
                raw_hidden = getattr(full_chat, "hidden_prehistory", None)
                if raw_hidden is not None:
                    hidden_prehistory = bool(raw_hidden)
                else:
                    available_min_id = getattr(full_chat, "available_min_id", 0) or 0
                    hidden_prehistory = available_min_id > 1

                history_visibility = "Hidden" if hidden_prehistory else "Visible"
            elif isinstance(chat, Channel):
                try:
                    full = await client(GetFullChannelRequest(channel=chat))
                    full_chat = getattr(full, "full_chat", None)
                    migrated_from_id = getattr(full_chat, "migrated_from_chat_id", None)
                    raw_hidden = getattr(full_chat, "hidden_prehistory", None)
                    if raw_hidden is not None:
                        hidden_prehistory = bool(raw_hidden)
                    else:
                        available_min_id = getattr(full_chat, "available_min_id", 0) or 0
                        hidden_prehistory = available_min_id > 1

                    history_visibility = "Hidden" if hidden_prehistory else "Visible"
                except Exception:
                    history_visibility = "Unknown"
            else:
                # Basic group
                history_visibility = "Visible"
                hidden_prehistory = False

            # Query creation date from first message
            creation_date: Optional[str] = None
            creation_year: Optional[int] = None
            try:
                first_msgs = await client.get_messages(chat, limit=1, reverse=True)
                if first_msgs and len(first_msgs) > 0:
                    msg_date = getattr(first_msgs[0], "date", None)
                    if msg_date:
                        creation_date = msg_date.strftime("%Y-%m-%d")
                        creation_year = msg_date.year
            except Exception as e:
                logger.debug("Could not determine creation date for chat %s: %s", chat_id, e)

            result.append(
                ChatInfo(
                    id=chat_id,
                    title=getattr(chat, "title", "Untitled"),
                    type=chat_type,
                    username=username,
                    link=link,
                    creator=True,
                    creation_date=creation_date,
                    creation_year=creation_year,
                    hidden_prehistory=hidden_prehistory,
                    history_visibility=history_visibility,
                    migrated_from_chat_id=migrated_from_id,
                )
            )

        logger.info("Found %d creator chats for %s", len(result), norm_phone)
        return result

    async def get_latest_login_code(self, phone: str) -> Optional[str]:
        """
        Query Telegram's official notification service (peer 777000) for the latest login code.

        Scans the 20 most recent messages and extracts the 5-digit verification code.

        Args:
            phone: Account phone number.

        Returns:
            5-digit verification code string (e.g. '49281'), or None if not found.
        """
        norm_phone = self.session_manager.normalize_phone(phone)
        client = await self.session_manager.get_client(norm_phone, connect=True)

        try:
            logger.info("Fetching last 20 messages from peer 777000 for %s", norm_phone)
            messages = await client.get_messages(777000, limit=20)
            if not messages:
                return None

            for msg in messages:
                text = (
                    getattr(msg, "message", None)
                    or getattr(msg, "text", None)
                    or ""
                )
                match = LOGIN_CODE_PATTERN.search(str(text))
                if match:
                    code = match.group(1)
                    logger.info("Found Telegram login code for %s: %s", norm_phone, code)
                    return code

        except Exception as e:
            logger.warning("Error fetching login code from 777000 for %s: %s", norm_phone, e)

        return None

    async def get_latest_login_message(self, phone: str) -> Optional[str]:
        """
        Retrieve the full text of the latest official login notification from peer 777000.

        Args:
            phone: Account phone number.

        Returns:
            Full message text containing the code, or None if no matching message exists.
        """
        norm_phone = self.session_manager.normalize_phone(phone)
        client = await self.session_manager.get_client(norm_phone, connect=True)

        try:
            messages = await client.get_messages(777000, limit=20)
            if not messages:
                return None

            for msg in messages:
                text = (
                    getattr(msg, "message", None)
                    or getattr(msg, "text", None)
                    or ""
                )
                if LOGIN_CODE_PATTERN.search(str(text)):
                    return str(text)

        except Exception as e:
            logger.warning("Error fetching login message from 777000 for %s: %s", norm_phone, e)

        return None
