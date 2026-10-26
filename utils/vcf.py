"""
utils.vcf
=========
In-memory streaming VCF (vCard) generator using io.BytesIO and vobject
for Telegram Account Manager.

Preserves exact legacy bot formatting:
- FN: Contact user ID (e.g., '1234567')
- N: Family name set to contact user ID, Given name empty (e.g., '1234567;;;;')
- TEL: Telephone number if available and non-empty (omitted if missing)
- Serialization: vCard 3.0 standard format
- Streaming: Writes UTF-8 bytes directly to io.BytesIO without writing temporary files to disk.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Union

import vobject


@dataclass
class ContactInfo:
    """
    Standardized contact information representation for Telegram accounts.

    Compatible with both Telethon User objects and custom contact queries.
    """

    id: Union[int, str]
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_mutual: bool = False


def _extract_id_and_phone(contact: Any) -> tuple[Optional[str], Optional[str]]:
    """
    Extract string contact ID and phone from a contact object or mapping.

    Args:
        contact: Contact instance (ContactInfo, Telethon User, dict, etc.)

    Returns:
        Tuple of (contact_id_str, phone_str). Either may be None.
    """
    if contact is None:
        return None, None

    cid: Any = None
    phone: Any = None

    if isinstance(contact, dict):
        cid = contact.get("id", contact.get("user_id"))
        phone = contact.get("phone")
    elif hasattr(contact, "id"):
        cid = getattr(contact, "id")
        phone = getattr(contact, "phone", None)
    elif hasattr(contact, "user_id"):
        cid = getattr(contact, "user_id")
        phone = getattr(contact, "phone", None)

    if cid is None:
        return None, None

    cid_str = str(cid).strip()
    if not cid_str:
        return None, None

    phone_str = str(phone).strip() if phone else None
    if phone_str == "":
        phone_str = None

    return cid_str, phone_str


def _build_vcard(contact_id: str, phone: Optional[str]) -> vobject.base.Component:
    """
    Construct a single vobject vCard matching original TG-ID.py formatting.

    Args:
        contact_id: Contact ID string used for FN and N family name.
        phone: Telephone number string if available.

    Returns:
        Configured vobject vCard component.
    """
    vcard = vobject.vCard()

    # Set full name to the ID
    vcard.add("fn").value = contact_id

    # Set name components: family name = ID, given name = empty
    vcard.add("n")
    vcard.n.value = vobject.vcard.Name(family=contact_id, given="")

    # Add telephone number only if available and non-empty
    if phone:
        tel = vcard.add("tel")
        tel.value = phone

    return vcard


def generate_vcf_content(contacts: Optional[Iterable[Any]]) -> str:
    """
    Generate complete VCF text content for the given contacts.

    Args:
        contacts: Iterable of contact objects.

    Returns:
        VCF formatted string containing all serialized vCards.
    """
    if not contacts:
        return ""

    cards: list[str] = []
    for contact in contacts:
        cid, phone = _extract_id_and_phone(contact)
        if not cid:
            continue
        vcard = _build_vcard(cid, phone)
        cards.append(vcard.serialize())

    return "".join(cards)


# Backward compatibility alias matching original TG-ID.py function name
create_vcf_from_contacts = generate_vcf_content


def generate_vcf_stream(
    contacts: Optional[Iterable[Any]], filename: Optional[str] = None
) -> io.BytesIO:
    """
    Generate an in-memory streaming VCF file as an io.BytesIO buffer.

    The returned buffer has its read pointer rewound to 0 (stream.seek(0))
    ready for direct delivery via python-telegram-bot's `send_document()`.

    Args:
        contacts: Iterable of contact objects.
        filename: Optional filename to attach to the stream (`stream.name = filename`).

    Returns:
        io.BytesIO containing serialized UTF-8 encoded VCF data.
    """
    stream = io.BytesIO()

    if contacts:
        for contact in contacts:
            cid, phone = _extract_id_and_phone(contact)
            if not cid:
                continue
            vcard = _build_vcard(cid, phone)
            stream.write(vcard.serialize().encode("utf-8"))

    # Rewind buffer to beginning for telegram bot reading
    stream.seek(0)

    if filename:
        stream.name = filename

    return stream


def format_vcf_filename(phone: str, id_length: Union[int, str]) -> str:
    """
    Format the standard VCF filename for digit-filtered contacts.

    Example:
        format_vcf_filename("+15156723850", 7) -> "+15156723850_7digit_contacts.vcf"
        format_vcf_filename("+15156723850", "7to9") -> "+15156723850_7to9digit_contacts.vcf"
    """
    return f"{phone}_{id_length}digit_contacts.vcf"


def format_mutual_vcf_filename(phone: str) -> str:
    """
    Format the standard VCF filename for mutual contacts export.

    Example:
        format_mutual_vcf_filename("+15156723850") -> "+15156723850_mutual_contacts.vcf"
    """
    return f"{phone}_mutual_contacts.vcf"
