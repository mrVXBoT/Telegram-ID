"""
Adversarial and Stress Test Suite for utils/phone.py and utils/filters.py.

Empirically verifies resilience against:
- Unicode whitespace variants (NBSP, en/em space, ideographic space, narrow NBSP)
- Invisible characters, BiDi marks, control chars, null bytes
- Exotic punctuation, multiple pluses, misplaced pluses, non-ASCII digits
- Boundary Value Analysis on phone digits (9, 10, 15, 16, extreme lengths)
- Type confusion, injection payloads, ReDoS resistance
- Country code extraction and fallback mechanism
- Duck typing across all supported and unsupported Python object models
- Negative IDs, zero IDs, float IDs, nan/inf, boolean IDs
- Generator inputs, custom iterators, empty iterables, None inputs
- Range specification edge cases, inverted ranges, malformed ranges
- High-volume stress testing (100,000 elements)
"""

from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass
import math
import sys
import time
from types import SimpleNamespace
from typing import Any, Iterator, Optional
import pytest

from utils.filters import (
    count_contacts_by_length,
    filter_contacts_by_digit_length,
    get_contact_id,
    get_contact_id_length,
    is_valid_contact_id,
    parse_length_spec,
)
from utils.phone import (
    get_country_code,
    is_valid_phone_number,
    sanitize_phone_number,
    validate_phone_number,
)


# ============================================================================
# Battery 1: Phone Sanitizer & Validator Adversarial Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone_input,expected",
    [
        # Standard non-breaking space (U+00A0)
        ("+1\u00a0515\u00a0672\u00a03850", "+15156723850"),
        # En-quad (U+2000), Em-quad (U+2001)
        ("+1\u2000515\u2001672\u20003850", "+15156723850"),
        # En-space (U+2002), Em-space (U+2003)
        ("+1\u2002515\u2003672\u20023850", "+15156723850"),
        # Three-per-em (U+2004), Four-per-em (U+2005), Six-per-em (U+2006)
        ("+1\u2004515\u2005672\u20063850", "+15156723850"),
        # Figure space (U+2007), Punctuation space (U+2008)
        ("+1\u2007515\u2008672\u20073850", "+15156723850"),
        # Thin space (U+2009), Hair space (U+200A)
        ("+1\u2009515\u200a672\u20093850", "+15156723850"),
        # Narrow no-break space (U+202F)
        ("+1\u202f515\u202f672\u202f3850", "+15156723850"),
        # Medium mathematical space (U+205F)
        ("+1\u205f515\u205f672\u205f3850", "+15156723850"),
        # Ideographic fullwidth space (U+3000)
        ("+1\u3000515\u3000672\u30003850", "+15156723850"),
        # ASCII control whitespace (\f, \v, \r, \n, \t)
        ("\r\n\t+1 515\f672\v3850\n", "+15156723850"),
        # Mixed standard and Unicode spaces
        ("  \u00a0+1 515\u3000672\u202f3850 \u2003 ", "+15156723850"),
    ],
)
def test_phone_unicode_whitespace_variants(phone_input: str, expected: str) -> None:
    """Verify all Unicode and ASCII whitespace variations are stripped during sanitization."""
    assert validate_phone_number(phone_input) == expected
    assert is_valid_phone_number(phone_input) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "malicious_phone",
    [
        # Zero-width space (U+200B)
        "+1515672\u200b3850",
        # LTR mark (U+200E) and RTL mark (U+200F)
        "\u200e+15156723850\u200f",
        # BiDi embedding / override marks (U+202A to U+202E)
        "\u202a+15156723850\u202c",
        # Byte order mark / Zero-width no-break space (U+FEFF)
        "\ufeff+15156723850",
        # Soft hyphen (U+00AD)
        "+1515\u00ad6723850",
        # Null byte injection
        "+15156723850\x00",
        # Terminal bell / escape characters
        "+15156723850\x07",
        "+15156723850\x1b[31m",
    ],
)
def test_phone_invisible_and_control_characters_rejected(malicious_phone: str) -> None:
    """Verify non-whitespace invisible Unicode and control characters are strictly rejected."""
    assert validate_phone_number(malicious_phone) is None
    assert is_valid_phone_number(malicious_phone) is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone_input,expected",
    [
        # Standard international formatting with parentheses and dots
        ("+1 (515) 672.3850", "+15156723850"),
        # Nested parentheses
        ("((+15156723850))", "+15156723850"),
        # Leading plus omitted with parentheses
        ("(515) 672-3850", "+5156723850"),
        # Dots only
        ("+1.515.672.3850", "+15156723850"),
        # Mixed dashes, dots, spaces, parens
        ("+1 (515) - 672 . 3850", "+15156723850"),
    ],
)
def test_phone_formatting_symbols_sanitized(phone_input: str, expected: str) -> None:
    """Verify standard parentheses, dashes, and dots are safely stripped."""
    assert validate_phone_number(phone_input) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone_input",
    [
        # Square brackets (not phone separators)
        "+1 [515] 672 3850",
        # Curly braces
        "+1 {515} 672 3850",
        # Angle brackets
        "+1 <515> 672 3850",
        # Slash / backslash
        "+1/515/672/3850",
        "+1\\515\\672\\3850",
        # Punctuation only
        "()",
        ".",
        "-(.)-",
        "....",
        "---",
    ],
)
def test_phone_invalid_symbols_rejected(phone_input: str) -> None:
    """Verify non-sanitizable symbols and punctuation-only inputs are rejected."""
    assert validate_phone_number(phone_input) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "phone_input",
    [
        "++15156723850",
        "+++15156723850",
        "+1+5156723850",
        "+15156723850+",
        "15156723850+",
        "+",
        "++",
        " + + ",
    ],
)
def test_phone_misplaced_or_multiple_pluses_rejected(phone_input: str) -> None:
    """Verify multiple or misplaced plus signs are strictly rejected."""
    assert validate_phone_number(phone_input) is None


@pytest.mark.unit
def test_phone_bva_digit_length_boundaries() -> None:
    """Verify Boundary Value Analysis bounds on phone digits (10 to 15 digits)."""
    # 9 digits (boundary - 1): must be None
    assert validate_phone_number("+123456789") is None
    assert validate_phone_number("123456789") is None

    # 10 digits (exact min bound): must succeed
    assert validate_phone_number("+1234567890") == "+1234567890"
    assert validate_phone_number("1234567890") == "+1234567890"

    # 11 to 14 digits (valid interior): must succeed
    assert validate_phone_number("+12345678901") == "+12345678901"
    assert validate_phone_number("+123456789012") == "+123456789012"
    assert validate_phone_number("+1234567890123") == "+1234567890123"
    assert validate_phone_number("+12345678901234") == "+12345678901234"

    # 15 digits (exact max bound): must succeed
    assert validate_phone_number("+123456789012345") == "+123456789012345"
    assert validate_phone_number("123456789012345") == "+123456789012345"

    # 16 digits (boundary + 1): must be None
    assert validate_phone_number("+1234567890123456") is None
    assert validate_phone_number("1234567890123456") is None

    # 20 digits: must be None
    assert validate_phone_number("+12345678901234567890") is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        "+15156723850'; DROP TABLE users;--",
        "+15156723850\nrm -rf /",
        "+15156723850<script>alert(1)</script>",
        "${7*7}+15156723850",
        "+15156723850%s%d%n",
        "{{config.items()}}",
    ],
)
def test_phone_injection_payloads_rejected(payload: str) -> None:
    """Verify SQL, shell, XSS, and template injection payloads are safely rejected."""
    assert validate_phone_number(payload) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "non_str_input",
    [
        None,
        15156723850,
        15156723850.0,
        float("nan"),
        float("inf"),
        float("-inf"),
        True,
        False,
        ["+15156723850"],
        ("+15156723850",),
        {"+15156723850"},
        {"phone": "+15156723850"},
        b"+15156723850",
        bytearray(b"+15156723850"),
        object(),
    ],
)
def test_phone_non_string_types_safe(non_str_input: Any) -> None:
    """Verify non-string types return None safely without raising exceptions."""
    assert validate_phone_number(non_str_input) is None
    assert is_valid_phone_number(non_str_input) is False
    assert sanitize_phone_number(non_str_input) == ""
    assert get_country_code(non_str_input) is None


@pytest.mark.unit
def test_phone_custom_str_subclass_handled() -> None:
    """Verify string subclasses are accepted, while objects with __str__ are rejected."""
    class CustomStr(str):
        pass

    class FakeStr:
        def __str__(self) -> str:
            return "+15156723850"

    assert validate_phone_number(CustomStr("+15156723850")) == "+15156723850"
    assert validate_phone_number(FakeStr()) is None


@pytest.mark.unit
def test_phone_country_code_fallback_and_boundaries() -> None:
    """Verify get_country_code works with diverse calling codes and survives fallback."""
    # US / Canada
    assert get_country_code("+15156723850") == 1
    # UK
    assert get_country_code("+447911123456") == 44
    # Iran
    assert get_country_code("+989123456789") == 98
    # Portugal (3-digit)
    assert get_country_code("+351912345678") == 351
    # Russia (1-digit 7)
    assert get_country_code("+79123456789") == 7
    # Germany (2-digit 49)
    assert get_country_code("+4915123456789") == 49
    # Australia (2-digit 61)
    assert get_country_code("+61412345678") == 61

    # Invalid / unassigned code
    assert get_country_code("+999123456789") is None
    # Invalid length
    assert get_country_code("+123") is None
    assert get_country_code("+1234567890123456") is None


@pytest.mark.unit
def test_phone_stress_and_redos_resistance() -> None:
    """Verify regexes resist ReDoS and handle large inputs in linear time."""
    # 50,000 spaces
    spaced = " " * 25000 + "+15156723850" + " " * 25000
    t0 = time.perf_counter()
    res = validate_phone_number(spaced)
    dt = time.perf_counter() - t0
    assert res == "+15156723850"
    assert dt < 0.1, f"Excessive sanitization time: {dt:.3f}s"

    # 100,000 digit string
    long_phone = "+" + "1" * 100000
    t0 = time.perf_counter()
    assert validate_phone_number(long_phone) is None
    dt = time.perf_counter() - t0
    assert dt < 0.1, f"Excessive validation time on 100k digits: {dt:.3f}s"

    # Repeated delimiters
    delims = "-(.)-" * 10000
    t0 = time.perf_counter()
    assert validate_phone_number(delims) is None
    dt = time.perf_counter() - t0
    assert dt < 0.1, f"Excessive validation time on delimiters: {dt:.3f}s"


# ============================================================================
# Battery 2: Contact Filters Adversarial Tests
# ============================================================================


@pytest.mark.unit
def test_filters_duck_typing_comprehensive() -> None:
    """Verify duck typing across Telethon User, Contact, dataclass, NamedTuple, SimpleNamespace, dict, int, str."""
    UserNT = namedtuple("UserNT", ["id"])
    ContactNT = namedtuple("ContactNT", ["user_id"])

    @dataclass
    class UserDC:
        id: int

    @dataclass
    class ContactDC:
        user_id: int

    class TelethonUser:
        def __init__(self, uid: int) -> None:
            self.id = uid

    class TelethonContact:
        def __init__(self, uid: int) -> None:
            self.user_id = uid

    class BothFields:
        def __init__(self, uid: int, other: int) -> None:
            self.id = uid
            self.user_id = other

    test_objects = [
        TelethonUser(1000001),
        TelethonContact(1000002),
        UserDC(1000003),
        ContactDC(1000004),
        UserNT(1000005),
        ContactNT(1000006),
        SimpleNamespace(id=1000007),
        SimpleNamespace(user_id=1000008),
        {"id": 1000009},
        {"user_id": 1000010},
        BothFields(1000011, 9999999),  # id should take precedence
        {"id": 1000012, "user_id": 8888888},
        1000013,
        "1000014",
        "  1000015  ",
    ]

    filtered = filter_contacts_by_digit_length(test_objects, 7)
    assert len(filtered) == len(test_objects)

    for obj in test_objects:
        assert is_valid_contact_id(obj) is True
        assert get_contact_id_length(obj) == 7


@pytest.mark.unit
def test_filters_unsupported_and_corrupt_objects() -> None:
    """Verify objects with corrupt, non-numeric, or missing IDs return None safely."""
    class EmptyObj:
        pass

    class MethodId:
        def id(self) -> int:
            return 1234567

    class AttributeErrorId:
        @property
        def id(self) -> int:
            raise AttributeError("id not available")

    corrupt_objects = [
        None,
        EmptyObj(),
        MethodId(),
        AttributeErrorId(),
        SimpleNamespace(id=None),
        SimpleNamespace(user_id=None),
        {"id": None},
        {"user_id": None},
        {"other": 1234567},
        "not_digits",
        "",
        "   ",
        [],
        {},
    ]

    for item in corrupt_objects:
        assert get_contact_id(item) is None
        assert is_valid_contact_id(item) is False
        assert get_contact_id_length(item) is None

    assert filter_contacts_by_digit_length(corrupt_objects, 7) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "negative_or_zero",
    [
        -1001234567890,  # Telegram supergroup/channel (-100...)
        -1234567890,     # Telegram basic group
        -1,
        0,
        "-1001234567890",
        "-1234567890",
        "-1",
        "0",
        {"id": -1001234567},
        {"user_id": 0},
    ],
)
def test_filters_negative_and_zero_ids_excluded(negative_or_zero: Any) -> None:
    """Verify negative channel/group IDs and zero IDs are excluded."""
    assert get_contact_id(negative_or_zero) is None
    assert is_valid_contact_id(negative_or_zero) is False
    assert filter_contacts_by_digit_length([negative_or_zero], 7) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "float_or_bool",
    [
        1234567.0,
        1234567.89,
        float("nan"),
        float("inf"),
        float("-inf"),
        True,
        False,
        {"id": 1234567.0},
        {"id": True},
        {"id": False},
        {"id": float("nan")},
    ],
)
def test_filters_floats_and_booleans_excluded(float_or_bool: Any) -> None:
    """Verify floats and booleans cannot masquerade as valid contact IDs."""
    assert get_contact_id(float_or_bool) is None
    assert is_valid_contact_id(float_or_bool) is False
    assert filter_contacts_by_digit_length([float_or_bool], 7) == []


@pytest.mark.unit
def test_filters_generator_and_iterator_support() -> None:
    """Verify filter_contacts_by_digit_length properly processes generators and iterators."""
    def gen_contacts() -> Iterator[dict[str, int]]:
        yield {"id": 1000000}
        yield {"id": 20000000}  # 8 digits
        yield {"id": 3000000}
        yield {"id": 400000000}  # 9 digits

    res_7 = filter_contacts_by_digit_length(gen_contacts(), 7)
    assert res_7 == [{"id": 1000000}, {"id": 3000000}]

    res_range = filter_contacts_by_digit_length(gen_contacts(), "7to9")
    assert len(res_range) == 4

    # Empty generator
    assert filter_contacts_by_digit_length((x for x in []), 7) == []

    # None input
    assert filter_contacts_by_digit_length(None, 7) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "spec,expected_min,expected_max",
    [
        (7, 7, 7),
        ("7", 7, 7),
        (" 7 ", 7, 7),
        (1, 1, 1),
        (15, 15, 15),
        ("7to9", 7, 9),
        ("7-9", 7, 9),
        ("7_9", 7, 9),
        (" 7to9 ", 7, 9),
        # Inverted ranges (should auto-swap)
        ("9to7", 7, 9),
        ("9-7", 7, 9),
        ("9_7", 7, 9),
        # Equal range
        ("7to7", 7, 7),
        # Max reasonable range
        ("1to15", 1, 15),
    ],
)
def test_filters_parse_length_spec_valid(spec: Any, expected_min: int, expected_max: int) -> None:
    """Verify parsing valid length specifications and ranges."""
    assert parse_length_spec(spec) == (expected_min, expected_max)


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_spec",
    [
        0,
        -1,
        -10,
        16,
        99,
        100,
        "0",
        "-1",
        "16",
        "99",
        "0to5",
        "5to0",
        "0to0",
        "1to16",
        "16to1",
        "16to20",
        "",
        "   ",
        "abc",
        "7to",
        "to9",
        "7to9to11",
        "7--9",
        "7__9",
        "7 to 9",
        None,
        7.0,
        8.5,
        [7, 9],
        {"min": 7},
    ],
)
def test_filters_parse_length_spec_invalid_raises_value_error(invalid_spec: Any) -> None:
    """Verify invalid length specifications raise ValueError."""
    with pytest.raises(ValueError):
        parse_length_spec(invalid_spec)


@pytest.mark.unit
def test_filters_count_contacts_by_length() -> None:
    """Verify count_contacts_by_length counts diverse IDs accurately."""
    contacts = [
        {"id": 1000000},       # 7
        {"id": 1000001},       # 7
        {"id": 10000000},      # 8
        {"id": 100000000},     # 9
        {"id": 1000000000},    # 10
        {"id": 10000000000},   # 11
        {"id": 100000},        # 6 (untracked)
        {"id": -1001234567},   # negative (ignored)
        None,                  # ignored
    ]

    counts = count_contacts_by_length(contacts)
    assert counts == {7: 2, 8: 1, 9: 1, 10: 1, 11: 1}

    # Custom lengths
    custom_counts = count_contacts_by_length(contacts, lengths=[6, 7])
    assert custom_counts == {6: 1, 7: 2}

    # None contacts
    assert count_contacts_by_length(None) == {7: 0, 8: 0, 9: 0, 10: 0, 11: 0}


@pytest.mark.unit
def test_filters_high_volume_stress() -> None:
    """Verify filtering and counting 100,000 items completes in < 500ms."""
    class UserItem:
        __slots__ = ("id",)

        def __init__(self, uid: int) -> None:
            self.id = uid

    def large_generator(n: int) -> Iterator[UserItem]:
        for i in range(n):
            yield UserItem(1000000 + i)

    # 100,000 items
    t0 = time.perf_counter()
    res = filter_contacts_by_digit_length(large_generator(100000), 7)
    dt = time.perf_counter() - t0
    assert len(res) == 100000
    assert dt < 0.5, f"Filtering 100k items took too long: {dt:.3f}s"

    t0 = time.perf_counter()
    counts = count_contacts_by_length(large_generator(100000))
    dt = time.perf_counter() - t0
    assert counts[7] == 100000
    assert dt < 0.5, f"Counting 100k items took too long: {dt:.3f}s"


# ============================================================================
# Battery 3: Randomized Fuzzing & Invariant Testing
# ============================================================================


@pytest.mark.unit
def test_phone_random_fuzzing_invariants() -> None:
    """Verify phone validator invariants across 1,000 randomly fuzzed character combinations."""
    import random
    import string

    chars = string.printable + string.whitespace + "+-.()[]{}!@#$%^&*_=;:/|0123456789" + "\u00a0\u200b\u200e\u200f\ufeff\u3000\x00\x1b"
    rng = random.Random(42)  # Deterministic seed

    for _ in range(1000):
        length = rng.randint(0, 40)
        raw = "".join(rng.choice(chars) for _ in range(length))

        # Invariant 1: No unhandled exceptions thrown
        val = validate_phone_number(raw)
        san = sanitize_phone_number(raw)
        cc = get_country_code(raw)

        # Invariant 2: If valid, format must strictly satisfy E.164-like constraints
        if val is not None:
            assert val.startswith("+"), f"Valid phone missing leading plus: {val}"
            assert 11 <= len(val) <= 16, f"Valid phone length out of bounds: {val}"
            assert val[1:].isdigit(), f"Non-digits in valid phone: {val}"
            assert is_valid_phone_number(raw) is True


@pytest.mark.unit
def test_filters_random_fuzzing_invariants() -> None:
    """Verify contact filter invariants across 1,000 randomly fuzzed object structures."""
    import random
    import string

    chars = string.printable + string.whitespace + "\u00a0\u200b\x00"
    rng = random.Random(42)

    class FuzzContainer:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    for _ in range(1000):
        choice = rng.randint(0, 6)
        val = rng.choice([
            rng.randint(-1000000000, 10000000000),
            "".join(rng.choice(chars) for _ in range(rng.randint(0, 15))),
            rng.random() * 1000000,
            None,
            True,
            False,
            object(),
        ])

        if choice == 0:
            c: Any = FuzzContainer(id=val)
        elif choice == 1:
            c = FuzzContainer(user_id=val)
        elif choice == 2:
            c = {"id": val}
        elif choice == 3:
            c = {"user_id": val}
        elif choice == 4:
            c = val
        elif choice == 5:
            c = FuzzContainer()
        else:
            c = None

        # Invariant 1: No unhandled exceptions thrown
        cid = get_contact_id(c)
        clen = get_contact_id_length(c)
        valid = is_valid_contact_id(c)

        # Invariant 2: If cid is extracted, it must be a strictly positive integer
        if cid is not None:
            assert isinstance(cid, int)
            assert cid > 0
            assert valid is True
            assert clen == len(str(cid))
        else:
            assert valid is False
            assert clen is None
