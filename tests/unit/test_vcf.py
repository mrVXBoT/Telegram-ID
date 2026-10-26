"""
Unit tests for utils/vcf.py.

Verifies:
- io.BytesIO stream return type and seek(0) rewound position
- vCard 3.0 formatting compliance (BEGIN/END, VERSION:3.0, FN, N, TEL)
- Multi-contact counting and batch output
- Round-trip parse validation with vobject library
- Immediate stream readability
- Empty contacts list handling
- Omission of TEL property when phone is None or empty string
- Duck typing on contacts lacking phone attribute
- UTF-8 and unicode character safety
- Zero temporary disk files created (pure in-memory)
- High-volume batch generation performance (<250ms for 500 contacts)
- Duck typing across Telethon User mock, SimpleNamespace, NamedTuple, and dict
"""

from __future__ import annotations

from collections import namedtuple
import io
import os
import time
from types import SimpleNamespace
from typing import Optional
import pytest
import vobject

from utils.vcf import ContactInfo, generate_vcf_stream


@pytest.mark.unit
def test_generate_vcf_stream_type_and_seek_position() -> None:
    """Verify generator returns an io.BytesIO stream with pointer at 0."""
    contacts = [
        ContactInfo(id=1234567, phone="+15156723850"),
        ContactInfo(id=2345678, phone="+15156723851"),
    ]
    stream = generate_vcf_stream(contacts)
    assert isinstance(stream, io.BytesIO)
    assert stream.tell() == 0


@pytest.mark.unit
def test_generate_vcf_single_contact_with_phone() -> None:
    """Verify single contact vCard contains all required vCard 3.0 properties."""
    contacts = [ContactInfo(id=1234567, phone="+15156723850")]
    stream = generate_vcf_stream(contacts)
    content = stream.read().decode("utf-8")

    assert "BEGIN:VCARD" in content
    assert "VERSION:3.0" in content
    assert "FN:1234567" in content
    assert "N:1234567;;;;" in content
    assert "TEL:+15156723850" in content
    assert "END:VCARD" in content


@pytest.mark.unit
def test_generate_vcf_multiple_contacts_count() -> None:
    """Verify exactly N vCards are generated for N contacts."""
    contacts = [
        ContactInfo(id=1000000 + i, phone=f"+1515672385{i}")
        for i in range(5)
    ]
    stream = generate_vcf_stream(contacts)
    content = stream.read().decode("utf-8")

    assert content.count("BEGIN:VCARD") == 5
    assert content.count("END:VCARD") == 5


@pytest.mark.unit
def test_generate_vcf_vobject_parse_validation() -> None:
    """Verify stream output can be round-trip parsed by vobject without errors."""
    contacts = [
        ContactInfo(id=1234567, phone="+15156723850"),
        ContactInfo(id=2345678, phone=None),
        ContactInfo(id=3456789, phone="+447911123456"),
    ]
    stream = generate_vcf_stream(contacts)
    cards = list(vobject.readComponents(stream.read().decode("utf-8")))

    assert len(cards) == 3
    assert cards[0].fn.value == "1234567"
    assert cards[0].tel.value == "+15156723850"
    assert cards[1].fn.value == "2345678"
    assert getattr(cards[1], "tel", None) is None
    assert cards[2].fn.value == "3456789"
    assert cards[2].tel.value == "+447911123456"


@pytest.mark.unit
def test_generate_vcf_headers_and_version_compliance() -> None:
    """Verify vCard version is explicitly 3.0."""
    stream = generate_vcf_stream([ContactInfo(id=1234567)])
    cards = list(vobject.readComponents(stream.read().decode("utf-8")))
    assert len(cards) == 1
    assert cards[0].version.value == "3.0"


@pytest.mark.unit
def test_generate_vcf_stream_read_content() -> None:
    """Verify stream is immediately readable from byte 0 without requiring manual seek."""
    stream = generate_vcf_stream([ContactInfo(id=1234567)])
    data = stream.read()
    assert len(data) > 0
    assert isinstance(data, bytes)


@pytest.mark.unit
def test_generate_vcf_empty_contacts_list() -> None:
    """Verify empty contacts list produces empty stream at tell=0 without error."""
    stream = generate_vcf_stream([])
    assert isinstance(stream, io.BytesIO)
    assert stream.tell() == 0
    assert stream.getvalue() == b""
    assert list(vobject.readComponents("")) == []


@pytest.mark.unit
def test_generate_vcf_contact_without_phone() -> None:
    """Verify contact with phone=None omits TEL property cleanly."""
    stream = generate_vcf_stream([ContactInfo(id=7654321, phone=None)])
    cards = list(vobject.readComponents(stream.read().decode("utf-8")))
    assert len(cards) == 1
    assert cards[0].fn.value == "7654321"
    assert getattr(cards[0], "tel", None) is None


@pytest.mark.unit
def test_generate_vcf_contact_with_empty_phone_string() -> None:
    """Verify contact with phone='' omits TEL property cleanly."""
    stream = generate_vcf_stream([ContactInfo(id=8765432, phone="")])
    cards = list(vobject.readComponents(stream.read().decode("utf-8")))
    assert len(cards) == 1
    assert getattr(cards[0], "tel", None) is None


@pytest.mark.unit
def test_generate_vcf_contact_missing_phone_attribute() -> None:
    """Verify duck-typed object without a phone attribute produces valid card omitting TEL."""
    contact = SimpleNamespace(id=9876543)
    stream = generate_vcf_stream([contact])
    cards = list(vobject.readComponents(stream.read().decode("utf-8")))
    assert len(cards) == 1
    assert cards[0].fn.value == "9876543"
    assert getattr(cards[0], "tel", None) is None


@pytest.mark.unit
def test_generate_vcf_unicode_and_special_chars() -> None:
    """Verify unicode names and formatted phones encode and decode cleanly."""
    contact = ContactInfo(
        id=1234567,
        phone="+1-515-672-3850",
        first_name="Тест",
        last_name="Али",
    )
    stream = generate_vcf_stream([contact])
    decoded = stream.read().decode("utf-8")
    assert len(decoded) > 0
    assert "FN:1234567" in decoded


@pytest.mark.unit
def test_generate_vcf_zero_disk_files_created() -> None:
    """Verify no files are written to disk during generation (zero disk leakage)."""
    before_files = set(os.listdir("."))
    stream = generate_vcf_stream([
        ContactInfo(id=i, phone=f"+1515672385{i}")
        for i in range(10)
    ])
    _ = stream.read()
    after_files = set(os.listdir("."))
    assert before_files == after_files


@pytest.mark.unit
def test_generate_vcf_large_batch_performance() -> None:
    """Verify high-volume batch (500 contacts) completes in under 250ms."""
    contacts = [
        ContactInfo(id=1000000 + i, phone=f"+1515672{i:04d}")
        for i in range(500)
    ]
    start = time.perf_counter()
    stream = generate_vcf_stream(contacts)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.25, f"Generation took {elapsed:.3f}s, expected < 0.250s"
    cards = list(vobject.readComponents(stream.read().decode("utf-8")))
    assert len(cards) == 500


@pytest.mark.unit
def test_generate_vcf_duck_typing() -> None:
    """Verify duck typing support for Telethon User mock, SimpleNamespace, NamedTuple, and dict."""
    UserNT = namedtuple("UserNT", ["id", "phone"])

    class TelethonUserMock:
        def __init__(self, uid: int, phone: Optional[str] = None) -> None:
            self.id = uid
            self.phone = phone

    c1 = TelethonUserMock(1234567, "+15156723850")
    c2 = SimpleNamespace(id=2345678, phone="+15156723851")
    c3 = UserNT(id=3456789, phone="+15156723852")
    c4 = {"id": 4567890, "phone": "+15156723853"}

    stream = generate_vcf_stream([c1, c2, c3, c4])
    cards = list(vobject.readComponents(stream.read().decode("utf-8")))

    assert len(cards) == 4
    assert cards[0].fn.value == "1234567"
    assert cards[0].tel.value == "+15156723850"
    assert cards[1].fn.value == "2345678"
    assert cards[1].tel.value == "+15156723851"
    assert cards[2].fn.value == "3456789"
    assert cards[2].tel.value == "+15156723852"
    assert cards[3].fn.value == "4567890"
    assert cards[3].tel.value == "+15156723853"
