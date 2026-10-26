"""
utils
=====
Core utility modules for Telegram Account Manager & Contact Extractor:
- phone: Validation, sanitization, and country code extraction.
- filters: Contact ID digit length filtering (single, range) and counting.
- vcf: In-memory streaming VCF generator and filename formatters.
"""

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
from utils.vcf import (
    ContactInfo,
    create_vcf_from_contacts,
    format_mutual_vcf_filename,
    format_vcf_filename,
    generate_vcf_content,
    generate_vcf_stream,
)

__all__ = [
    # phone
    "sanitize_phone_number",
    "validate_phone_number",
    "is_valid_phone_number",
    "get_country_code",
    # filters
    "get_contact_id",
    "is_valid_contact_id",
    "get_contact_id_length",
    "parse_length_spec",
    "filter_contacts_by_digit_length",
    "count_contacts_by_length",
    # vcf
    "ContactInfo",
    "generate_vcf_content",
    "generate_vcf_stream",
    "create_vcf_from_contacts",
    "format_vcf_filename",
    "format_mutual_vcf_filename",
]
