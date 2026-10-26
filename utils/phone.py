"""
utils.phone
===========
Phone number sanitization, validation, and country code extraction utilities
for Telegram Account Manager.

Matches original bot behavior with enhanced edge case resilience:
- Strips whitespace, dashes, parentheses, dots.
- Guarantees leading '+' prefix.
- Validates international phone format with regex: ^\\+[0-9]{10,15}$ (E.164 compliance).
- Strictly enforces ASCII digits to ensure compatibility with Telethon MTProto.
- Provides country code extraction with phonenumbers fallback.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# E.164-like international regex: + followed by 10 to 15 ASCII digits
PHONE_REGEX = re.compile(r"^\+[0-9]{10,15}$")

# Characters to strip during sanitization: whitespace, dashes, parentheses, dots
CLEAN_REGEX = re.compile(r"[\s\-().]")


def sanitize_phone_number(phone: Any) -> str:
    """
    Sanitize phone number by removing spaces, dashes, parentheses, and dots,
    and ensuring a single leading '+' sign.

    Args:
        phone: Raw phone input. Must be a string.

    Returns:
        Sanitized phone string with leading '+', or empty string if invalid input.
    """
    if phone is None or not isinstance(phone, str):
        return ""

    phone_str = phone.strip()
    if not phone_str:
        return ""

    cleaned = CLEAN_REGEX.sub("", phone_str)
    if not cleaned:
        return ""

    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned

    return cleaned


def validate_phone_number(phone: Any) -> Optional[str]:
    """
    Validate and normalize a phone number according to international format.

    Rules:
    - Must be a string (non-strings return None).
    - Strips whitespace, dashes, parentheses, dots.
    - Prepends '+' if omitted.
    - Requires 10 to 15 ASCII digits following '+'.
    - Rejects non-ASCII digits (e.g. Persian/Arabic), letters, special symbols,
      extra pluses, or out-of-range lengths.

    Args:
        phone: Phone number to validate.

    Returns:
        Normalized phone string (e.g., '+15156723850') if valid, else None.
    """
    if phone is None or not isinstance(phone, str):
        return None

    cleaned = sanitize_phone_number(phone)
    if not cleaned:
        return None

    if PHONE_REGEX.match(cleaned):
        return cleaned

    return None


def is_valid_phone_number(phone: Any) -> bool:
    """Check if phone number is valid."""
    return validate_phone_number(phone) is not None


def get_country_code(phone: Any) -> Optional[int]:
    """
    Extract the country calling code from a valid phone number.

    Uses `phonenumbers` if available; otherwise falls back to a common prefix table.

    Args:
        phone: Phone number to inspect.

    Returns:
        Integer country code (e.g. 1 for US/CA, 98 for Iran, 44 for UK), or None.
    """
    normalized = validate_phone_number(phone)
    if not normalized:
        return None

    # Try phonenumbers library first if available
    try:
        import phonenumbers  # type: ignore

        parsed = phonenumbers.parse(normalized)
        return int(parsed.country_code)
    except Exception:
        pass

    # Built-in fallback for major common calling codes
    digits = normalized[1:]  # strip leading '+'
    # 3-digit prefixes
    three_digit_codes = {
        "351", "352", "353", "354", "355", "356", "357", "358", "359",
        "370", "371", "372", "373", "374", "375", "376", "377", "378",
        "380", "381", "382", "385", "386", "387", "389",
    }
    # 2-digit prefixes
    two_digit_codes = {
        "20", "27", "30", "31", "32", "33", "34", "36", "39", "40",
        "41", "43", "44", "45", "46", "47", "48", "49", "51", "52",
        "53", "54", "55", "56", "57", "58", "60", "61", "62", "63",
        "64", "65", "66", "81", "82", "84", "86", "90", "91", "92",
        "93", "94", "95", "98",
    }

    if digits[:3] in three_digit_codes:
        return int(digits[:3])
    if digits[:2] in two_digit_codes:
        return int(digits[:2])
    if digits[:1] in {"1", "7"}:
        return int(digits[:1])

    return None
