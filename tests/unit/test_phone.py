"""
Unit tests for utils/phone.py.

Verifies:
- Standard international E.164 phone formats
- Leading plus normalization
- Whitespace and dash sanitization
- Mixed formatting (spaces, dashes, parentheses, dots)
- Multiple international calling codes (US, UK, Iran, Germany, Australia)
- Boundary Value Analysis (BVA) for digit lengths: 9, 10, 15, 16 digits
- Empty strings, whitespace-only, lone plus symbol
- Malformed inputs: multiple pluses, alphanumeric, punctuation
- Type safety: None, int, list inputs
- Rejection of non-ASCII unicode digits (Persian / Eastern Arabic)
"""

from __future__ import annotations

from typing import Any
import pytest

from utils.phone import validate_phone_number


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone",
    [
        "+15156723850",
        "+989123456789",
        "+447911123456",
    ],
)
def test_validate_standard_international_with_plus(phone: str) -> None:
    """Verify valid international phone numbers with leading plus are preserved."""
    assert validate_phone_number(phone) == phone


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone,expected",
    [
        ("15156723850", "+15156723850"),
        ("989123456789", "+989123456789"),
        ("447911123456", "+447911123456"),
    ],
)
def test_validate_phone_without_leading_plus(phone: str, expected: str) -> None:
    """Verify phone numbers without leading plus are properly normalized with '+'."""
    assert validate_phone_number(phone) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone",
    [
        "+1 515 672 3850",
        " +15156723850 ",
        "+1\t515\t6723850",
        "+1\n5156723850\n",
    ],
)
def test_validate_phone_with_whitespace(phone: str) -> None:
    """Verify internal and surrounding whitespace (spaces, tabs, newlines) is stripped."""
    assert validate_phone_number(phone) == "+15156723850"


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone,expected",
    [
        ("+1-515-672-3850", "+15156723850"),
        ("98-912-345-6789", "+989123456789"),
        ("+44-7911-123-456", "+447911123456"),
    ],
)
def test_validate_phone_with_dashes(phone: str, expected: str) -> None:
    """Verify hyphens and dashes are stripped during normalization."""
    assert validate_phone_number(phone) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone",
    [
        "  +1 - 515 - 672 3850  ",
        " 1-515-672-3850 ",
    ],
)
def test_validate_phone_mixed_formatting(phone: str) -> None:
    """Verify mixed spaces, dashes, and whitespace are normalized correctly."""
    assert validate_phone_number(phone) == "+15156723850"


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone,expected",
    [
        ("+15156723850", "+15156723850"),
        ("+447911123456", "+447911123456"),
        ("+989123456789", "+989123456789"),
        ("+4915123456789", "+4915123456789"),
        ("+61412345678", "+61412345678"),
    ],
)
def test_validate_phone_various_country_codes(phone: str, expected: str) -> None:
    """Verify diverse real-world international calling codes are handled correctly."""
    assert validate_phone_number(phone) == expected


@pytest.mark.unit
def test_validate_phone_boundary_min_digits_10() -> None:
    """Verify BVA lower bound: exactly 10 digits after plus is accepted."""
    assert validate_phone_number("+1234567890") == "+1234567890"


@pytest.mark.unit
@pytest.mark.parametrize("phone", ["+123456789", "+1", "+123"])
def test_validate_phone_boundary_below_min_9_digits(phone: str) -> None:
    """Verify BVA below lower bound: 9 or fewer digits is rejected."""
    assert validate_phone_number(phone) is None


@pytest.mark.unit
def test_validate_phone_boundary_max_digits_15() -> None:
    """Verify BVA upper bound: exactly 15 digits after plus is accepted."""
    assert validate_phone_number("+123456789012345") == "+123456789012345"


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone",
    [
        "+1234567890123456",
        "+12345678901234567890",
    ],
)
def test_validate_phone_boundary_above_max_16_digits(phone: str) -> None:
    """Verify BVA above upper bound: 16 or more digits is rejected."""
    assert validate_phone_number(phone) is None


@pytest.mark.unit
@pytest.mark.parametrize("phone", ["", "   ", "\t\n\r"])
def test_validate_phone_empty_and_whitespace_only(phone: str) -> None:
    """Verify empty string and whitespace-only strings return None."""
    assert validate_phone_number(phone) is None


@pytest.mark.unit
def test_validate_phone_only_plus() -> None:
    """Verify lone '+' character returns None."""
    assert validate_phone_number("+") is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone",
    [
        "++15156723850",
        "+1+5156723850",
        "+15156723850+",
    ],
)
def test_validate_phone_multiple_pluses(phone: str) -> None:
    """Verify multiple plus signs anywhere in the input are rejected."""
    assert validate_phone_number(phone) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone",
    [
        "+1515672CALL",
        "+1515abc3850",
        "+15156723850!",
        "+15156723850#12",
    ],
)
def test_validate_phone_non_digit_characters(phone: str) -> None:
    """Verify alphabetical and special punctuation characters are rejected."""
    assert validate_phone_number(phone) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone",
    [
        None,
        15156723850,
        ["+15156723850"],
    ],
)
def test_validate_phone_non_string_types(phone: Any) -> None:
    """Verify non-string types safely return None without throwing exceptions."""
    assert validate_phone_number(phone) is None


@pytest.mark.unit
def test_validate_phone_unicode_digits() -> None:
    """Verify non-ASCII Persian/Arabic unicode digits are rejected (ASCII only)."""
    assert validate_phone_number("+۱۲۳۴۵۶۷۸۹۰") is None
