"""
Unit tests for utils/filters.py.

Verifies:
- Exact single-digit length filtering (7, 8, 9, 10, 11) with int and str specs
- Bulk range filtering ('7to9')
- Empty list and no-match handling
- Order preservation and immutability of input iterable
- BVA boundaries for '7to9' range (6, 7, 9, 10 digits)
- Exclusion of negative channel/group IDs (-100...)
- Exclusion of non-numeric strings ('admin', etc.)
- Handling of numeric string IDs ('1234567')
- Graceful handling of None or missing id attributes
- ValueError raising on invalid length specifications ('abc', 0, -1, 99, None)
- Support for arbitrary iterables (generators, tuples, sets)
- Duck typing support across various object structures (Telethon User, NamedTuple, SimpleNamespace, dict)
"""

from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional
import pytest

from utils.filters import filter_contacts_by_digit_length


@dataclass(frozen=True)
class MockContact:
    """Mock contact model for filtering tests."""

    id: Any
    phone: Optional[str] = None


@pytest.mark.unit
def test_filter_contacts_exact_length_7() -> None:
    """Verify filtering contacts with exactly 7-digit IDs using int and str."""
    contacts = [
        MockContact(123456),      # 6 digits
        MockContact(1234567),     # 7 digits
        MockContact(12345678),    # 8 digits
        MockContact(123456789),   # 9 digits
        MockContact(1234567890),  # 10 digits
    ]
    res_int = filter_contacts_by_digit_length(contacts, 7)
    res_str = filter_contacts_by_digit_length(contacts, "7")
    assert res_int == [contacts[1]]
    assert res_str == [contacts[1]]


@pytest.mark.unit
def test_filter_contacts_exact_length_8() -> None:
    """Verify filtering contacts with exactly 8-digit IDs using int and str."""
    contacts = [
        MockContact(1234567),     # 7 digits
        MockContact(12345678),    # 8 digits
        MockContact(123456789),   # 9 digits
    ]
    res_int = filter_contacts_by_digit_length(contacts, 8)
    res_str = filter_contacts_by_digit_length(contacts, "8")
    assert res_int == [contacts[1]]
    assert res_str == [contacts[1]]


@pytest.mark.unit
def test_filter_contacts_exact_length_9() -> None:
    """Verify filtering contacts with exactly 9-digit IDs using int and str."""
    contacts = [
        MockContact(12345678),    # 8 digits
        MockContact(123456789),   # 9 digits
        MockContact(1234567890),  # 10 digits
    ]
    res_int = filter_contacts_by_digit_length(contacts, 9)
    res_str = filter_contacts_by_digit_length(contacts, "9")
    assert res_int == [contacts[1]]
    assert res_str == [contacts[1]]


@pytest.mark.unit
def test_filter_contacts_exact_length_10() -> None:
    """Verify filtering contacts with exactly 10-digit IDs using int and str."""
    contacts = [
        MockContact(123456789),   # 9 digits
        MockContact(1234567890),  # 10 digits
        MockContact(12345678901), # 11 digits
    ]
    res_int = filter_contacts_by_digit_length(contacts, 10)
    res_str = filter_contacts_by_digit_length(contacts, "10")
    assert res_int == [contacts[1]]
    assert res_str == [contacts[1]]


@pytest.mark.unit
def test_filter_contacts_exact_length_11() -> None:
    """Verify filtering contacts with exactly 11-digit IDs using int and str."""
    contacts = [
        MockContact(1234567890),   # 10 digits
        MockContact(12345678901),  # 11 digits
        MockContact(123456789012), # 12 digits
    ]
    res_int = filter_contacts_by_digit_length(contacts, 11)
    res_str = filter_contacts_by_digit_length(contacts, "11")
    assert res_int == [contacts[1]]
    assert res_str == [contacts[1]]


@pytest.mark.unit
def test_filter_contacts_bulk_range_7to9() -> None:
    """Verify filtering contacts in range 7 to 9 digits inclusive with '7to9'."""
    contacts = [
        MockContact(123456),       # 6 digits
        MockContact(1234567),      # 7 digits
        MockContact(12345678),     # 8 digits
        MockContact(123456789),    # 9 digits
        MockContact(1234567890),   # 10 digits
        MockContact(12345678901),  # 11 digits
    ]
    res = filter_contacts_by_digit_length(contacts, "7to9")
    assert res == [contacts[1], contacts[2], contacts[3]]


@pytest.mark.unit
def test_filter_contacts_empty_list() -> None:
    """Verify filtering an empty list returns an empty list without error."""
    assert filter_contacts_by_digit_length([], 7) == []
    assert filter_contacts_by_digit_length([], "7to9") == []


@pytest.mark.unit
def test_filter_contacts_no_matches() -> None:
    """Verify filtering contacts when no ID matches the criteria returns empty list."""
    contacts = [MockContact(1234567890), MockContact(9876543210)]
    assert filter_contacts_by_digit_length(contacts, 7) == []


@pytest.mark.unit
def test_filter_contacts_preserves_order() -> None:
    """Verify the original sequence order of contacts is strictly preserved."""
    c1 = MockContact(1111111)
    c2 = MockContact(2222222)
    c3 = MockContact(3333333)
    contacts = [c1, c2, c3]
    assert filter_contacts_by_digit_length(contacts, 7) == [c1, c2, c3]


@pytest.mark.unit
def test_filter_contacts_does_not_mutate_input() -> None:
    """Verify filtering does not mutate the source contact list and returns a new list."""
    orig = [MockContact(1111111), MockContact(2222222)]
    copy_orig = list(orig)
    res = filter_contacts_by_digit_length(orig, 7)
    assert orig == copy_orig
    assert res is not orig


@pytest.mark.unit
def test_filter_contacts_7to9_boundary_values() -> None:
    """Verify BVA bounds for '7to9': 6-digit and 10-digit excluded, 7-digit and 9-digit included."""
    b_contacts = [
        MockContact(999999),      # 6 digits (boundary - 1)
        MockContact(1000000),     # 7 digits (exact lower bound)
        MockContact(999999999),   # 9 digits (exact upper bound)
        MockContact(1000000000),  # 10 digits (boundary + 1)
    ]
    res = filter_contacts_by_digit_length(b_contacts, "7to9")
    assert res == [b_contacts[1], b_contacts[2]]


@pytest.mark.unit
def test_filter_contacts_negative_ids_excluded() -> None:
    """Verify negative IDs (such as channel/group IDs -100...) are excluded."""
    neg = [MockContact(-1001234567), MockContact(-1234567)]
    assert filter_contacts_by_digit_length(neg, 7) == []
    assert filter_contacts_by_digit_length(neg, 10) == []


@pytest.mark.unit
def test_filter_contacts_non_numeric_ids_excluded() -> None:
    """Verify non-numeric string IDs are excluded without error."""
    non_num = [MockContact("admin"), MockContact("user_1234567"), MockContact("")]
    assert filter_contacts_by_digit_length(non_num, 7) == []


@pytest.mark.unit
def test_filter_contacts_numeric_string_ids() -> None:
    """Verify string IDs containing only numeric digits are matched correctly."""
    str_contact = MockContact("1234567")
    assert filter_contacts_by_digit_length([str_contact], 7) == [str_contact]


@pytest.mark.unit
def test_filter_contacts_none_or_missing_id() -> None:
    """Verify objects with id=None or missing id attribute are skipped gracefully."""

    class MissingId:
        pass

    valid = MockContact(1234567)
    mixed = [MockContact(None), MissingId(), valid]
    assert filter_contacts_by_digit_length(mixed, 7) == [valid]


@pytest.mark.unit
@pytest.mark.parametrize("invalid_spec", ["abc", 0, -1, 99, None])
def test_filter_contacts_invalid_length_spec_raises_value_error(invalid_spec: Any) -> None:
    """Verify invalid, non-positive, or out-of-range length specs raise ValueError."""
    with pytest.raises(ValueError):
        filter_contacts_by_digit_length([MockContact(1234567)], invalid_spec)


@pytest.mark.unit
def test_filter_contacts_accepts_generators_and_iterables() -> None:
    """Verify filter accepts generators, tuples, and sets as input."""
    contacts = [MockContact(1234567), MockContact(7654321)]
    # Generator
    res_gen = filter_contacts_by_digit_length((c for c in contacts), 7)
    assert res_gen == contacts
    # Tuple
    res_tup = filter_contacts_by_digit_length(tuple(contacts), 7)
    assert res_tup == contacts
    # Set
    res_set = filter_contacts_by_digit_length(set(contacts), 7)
    assert len(res_set) == 2


@pytest.mark.unit
def test_filter_contacts_duck_typing() -> None:
    """Verify duck typing across mock Telethon User, SimpleNamespace, NamedTuple, and dict."""
    UserNT = namedtuple("UserNT", ["id", "phone"])

    class TelethonUserMock:
        def __init__(self, uid: int, phone: Optional[str] = None) -> None:
            self.id = uid
            self.phone = phone

    c1 = TelethonUserMock(1234567)
    c2 = SimpleNamespace(id=2345678)
    c3 = UserNT(id=3456789, phone="+15156723850")
    c4 = {"id": 4567890}

    res = filter_contacts_by_digit_length([c1, c2, c3, c4], 7)
    assert res == [c1, c2, c3, c4]
