"""
utils.filters
=============
Contact ID digit length filtering and analysis functions for Telegram Account Manager.

Supports:
- Single digit length filtering: 7, 8, 9, 10, 11 digits (int or str)
- Bulk range filtering: '7to9', '7-9', '7_9'
- Arbitrary range parsing: 'MtoN', 'M-N', 'M_N'
- Resilient duck-typing handling: Telethon User objects, dataclasses, dicts, raw values.
- Edge case handling: Non-numeric IDs, negative IDs, strings vs ints, None values, empty lists.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional, Union

# Pattern matching range queries like '7to9', '7-9', '7_9'
RANGE_PATTERN = re.compile(r"^(\d+)(?:to|-|_)(\d+)$")

# Maximum reasonable digit length for Telegram user IDs (64-bit int user IDs are <= 15 digits)
MAX_DIGIT_LENGTH = 15


def get_contact_id(contact: Any) -> Optional[int]:
    """
    Safely extract numeric contact ID from diverse object structures.

    Supported structures:
    - Object with `.id` attribute (Telethon User, ContactInfo)
    - Object with `.user_id` attribute (Telethon Contact)
    - Mapping/dict with `'id'` or `'user_id'` keys
    - Raw int or numeric str

    Rejects non-numeric, negative (group/channel IDs), or empty values.

    Args:
        contact: Contact representation or ID.

    Returns:
        Positive integer contact ID, or None if invalid.
    """
    if contact is None:
        return None

    raw: Any = None
    if isinstance(contact, dict):
        raw = contact.get("id", contact.get("user_id"))
    elif hasattr(contact, "id"):
        raw = getattr(contact, "id")
    elif hasattr(contact, "user_id"):
        raw = getattr(contact, "user_id")
    elif isinstance(contact, (int, str)):
        raw = contact

    if raw is None:
        return None

    raw_str = str(raw).strip()
    # User IDs in Telegram are positive integers; negative values correspond to chats/channels
    if raw_str.isdigit() and not raw_str.startswith("-"):
        val = int(raw_str)
        if val > 0:
            return val

    return None


def is_valid_contact_id(contact_id: Any) -> bool:
    """Check if the provided contact ID is a valid numeric Telegram user ID."""
    return get_contact_id(contact_id) is not None


def get_contact_id_length(contact: Any) -> Optional[int]:
    """
    Get the digit length of a contact's ID.

    Args:
        contact: Contact object or ID.

    Returns:
        Number of digits in contact ID, or None if invalid.
    """
    cid = get_contact_id(contact)
    if cid is not None:
        return len(str(cid))
    return None


def parse_length_spec(length_spec: Union[int, str]) -> tuple[int, int]:
    """
    Parse a length query specification into inclusive (min_length, max_length).

    Supported formats:
    - Single integer: 7 -> (7, 7)
    - Single digit string: '7' -> (7, 7)
    - Range string: '7to9', '7-9', '7_9' -> (7, 9)

    Args:
        length_spec: Length query specification.

    Returns:
        Tuple of (min_length, max_length) inclusive.

    Raises:
        ValueError: If length_spec is invalid, non-positive, or out of range.
    """
    if length_spec is None:
        raise ValueError("length_spec cannot be None")

    if isinstance(length_spec, int):
        if length_spec <= 0 or length_spec > MAX_DIGIT_LENGTH:
            raise ValueError(f"Length specification must be between 1 and {MAX_DIGIT_LENGTH}, got {length_spec}")
        return (length_spec, length_spec)

    if isinstance(length_spec, str):
        spec = length_spec.strip().lower()
        if spec.isdigit():
            val = int(spec)
            if val <= 0 or val > MAX_DIGIT_LENGTH:
                raise ValueError(f"Length specification must be between 1 and {MAX_DIGIT_LENGTH}, got {val}")
            return (val, val)

        range_match = RANGE_PATTERN.match(spec)
        if range_match:
            min_len = int(range_match.group(1))
            max_len = int(range_match.group(2))
            if min_len <= 0 or max_len <= 0 or min_len > MAX_DIGIT_LENGTH or max_len > MAX_DIGIT_LENGTH:
                raise ValueError(f"Range limits must be between 1 and {MAX_DIGIT_LENGTH}: {length_spec}")
            if min_len > max_len:
                min_len, max_len = max_len, min_len
            return (min_len, max_len)

    raise ValueError(f"Unsupported length specification: {length_spec!r}")


def filter_contacts_by_digit_length(
    contacts: Optional[Iterable[Any]], length_spec: Union[int, str]
) -> list[Any]:
    """
    Filter contacts whose Telegram user ID length matches the specified length or range.

    Args:
        contacts: Iterable of contact objects (Telethon Users, ContactInfo, dicts, etc.).
        length_spec: Target digit length (e.g. 7, 8, 9, 10, 11) or range ('7to9').

    Returns:
        List of matching contact objects in original order.
        Returns empty list if contacts is empty or None.

    Raises:
        ValueError: If length_spec is invalid.
    """
    if contacts is None:
        return []

    min_len, max_len = parse_length_spec(length_spec)
    filtered = []

    for contact in contacts:
        if contact is None:
            continue
        id_len = get_contact_id_length(contact)
        if id_len is not None and min_len <= id_len <= max_len:
            filtered.append(contact)

    return filtered


def count_contacts_by_length(
    contacts: Optional[Iterable[Any]],
    lengths: Optional[Iterable[int]] = None,
) -> dict[int, int]:
    """
    Count contacts categorized by their ID digit lengths.

    Args:
        contacts: Iterable of contact objects.
        lengths: Specific lengths to count (default: 7, 8, 9, 10, 11).

    Returns:
        Dictionary mapping length to contact count.
    """
    target_lengths = list(lengths) if lengths is not None else [7, 8, 9, 10, 11]
    counts: dict[int, int] = {length: 0 for length in target_lengths}

    if not contacts:
        return counts

    for contact in contacts:
        if contact is None:
            continue
        id_len = get_contact_id_length(contact)
        if id_len is not None and id_len in counts:
            counts[id_len] += 1

    return counts
