"""
Adversarial stress and edge-case test harness for utils/vcf.py and config/settings.py.
Milestone 1.2 Empirical Challenge.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import concurrent.futures
from dataclasses import dataclass
import gc
import io
import os
import shutil
import time
import tracemalloc
from types import SimpleNamespace
from typing import Any, Optional
import pytest
from pydantic import ValidationError
import vobject

from config.settings import Settings, get_settings
from utils.vcf import (

    ContactInfo,
    generate_vcf_stream,
    generate_vcf_content,
    format_vcf_filename,
    format_mutual_vcf_filename,
)


# =====================================================================
# VCF GENERATOR STRESS TESTS
# =====================================================================

@pytest.mark.slow
def test_vcf_5000_contacts_performance_and_memory() -> None:
    """Stress test generation of 5,000 contacts: memory, speed, tell() == 0, RFC compliance."""
    contacts = [
        ContactInfo(id=1000000 + i, phone=f"+1555000{i:04d}")
        for i in range(5000)
    ]

    gc.collect()
    tracemalloc.start()
    start_time = time.perf_counter()

    stream = generate_vcf_stream(contacts, filename="batch_5000.vcf")

    duration = time.perf_counter() - start_time
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Empirical assertions
    assert isinstance(stream, io.BytesIO), "Expected io.BytesIO stream"
    assert stream.tell() == 0, f"Expected tell() == 0, got {stream.tell()}"
    assert stream.name == "batch_5000.vcf"

    raw_data = stream.read()
    assert len(raw_data) > 0, "Stream must not be empty"

    # Memory and duration bounds
    peak_mb = peak_mem / (1024 * 1024)
    print(f"\n[STRESS 5k] Duration: {duration:.3f}s | Peak Mem: {peak_mb:.2f} MB | Size: {len(raw_data)/1024:.1f} KB")

    # 5,000 contacts generation benchmark (pure-python vobject serialization)
    assert duration < 10.0, f"5,000 contacts took {duration:.2f}s (> 10.0s limit)"

    # Peak memory overhead for 5,000 contacts should be under 20 MB
    assert peak_mb < 20.0, f"Peak memory {peak_mb:.2f} MB exceeds 20 MB limit"

    # RFC 2426 format compliance
    decoded = raw_data.decode("utf-8")
    assert decoded.count("BEGIN:VCARD") == 5000
    assert decoded.count("END:VCARD") == 5000
    assert decoded.count("VERSION:3.0") == 5000


@pytest.mark.slow
def test_vcf_10000_contacts_scale_and_tell_zero() -> None:
    """Stress test generation of 10,000 contacts: memory scaling and strict stream rewind."""
    contacts = [
        ContactInfo(id=2000000 + i, phone=f"+188800{i:05d}")
        for i in range(10000)
    ]

    gc.collect()
    tracemalloc.start()
    start_time = time.perf_counter()

    stream = generate_vcf_stream(contacts, filename="+18880000000_10000_contacts.vcf")

    duration = time.perf_counter() - start_time
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert stream.tell() == 0, f"stream pointer must be at 0, got {stream.tell()}"
    assert stream.name == "+18880000000_10000_contacts.vcf"

    raw_data = stream.read()
    peak_mb = peak_mem / (1024 * 1024)
    print(f"\n[STRESS 10k] Duration: {duration:.3f}s | Peak Mem: {peak_mb:.2f} MB | Size: {len(raw_data)/1024:.1f} KB")

    assert duration < 25.0, f"10,000 contacts took {duration:.2f}s (> 25.0s limit)"
    assert peak_mb < 35.0, f"Peak memory {peak_mb:.2f} MB exceeds 35 MB limit"


    decoded = raw_data.decode("utf-8")
    assert decoded.count("BEGIN:VCARD") == 10000
    assert decoded.count("END:VCARD") == 10000
    assert decoded.startswith("BEGIN:VCARD")
    assert decoded.rstrip().endswith("END:VCARD")


@pytest.mark.slow
def test_vcf_memory_leak_across_iterations() -> None:
    """Verify repeated high-volume VCF generation does not leak memory across iterations."""
    gc.collect()
    contacts = [ContactInfo(id=3000000 + i, phone=f"+1777000{i:04d}") for i in range(2000)]

    # Warmup
    _ = generate_vcf_stream(contacts)
    gc.collect()

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    for _ in range(8):
        stream = generate_vcf_stream(contacts)
        _ = stream.read()
        del stream

    gc.collect()
    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = snapshot_after.compare_to(snapshot_before, "lineno")
    total_diff_kb = sum(stat.size_diff for stat in stats) / 1024
    print(f"\n[LEAK TEST] Memory diff across 8 runs: {total_diff_kb:.2f} KB")

    # Total uncollected memory difference across 8 runs of 2,000 contacts should be under 500 KB
    assert total_diff_kb < 500, f"Possible memory leak detected: {total_diff_kb:.2f} KB retained"


@pytest.mark.unit
def test_vcf_rfc2426_format_compliance() -> None:
    """Verify compliance with RFC 2426 vCard 3.0 specification: CRLF line breaks, valid properties."""
    contacts = [
        ContactInfo(id=4567890, phone="+15551234567"),
        ContactInfo(id=5678901, phone=None),
    ]

    stream = generate_vcf_stream(contacts)
    raw_bytes = stream.read()

    # RFC 2426 specifies CRLF line terminators
    assert b"\r\n" in raw_bytes, "RFC 2426 requires CRLF line terminators"

    # Round trip parse with vobject
    text = raw_bytes.decode("utf-8")
    cards = list(vobject.readComponents(text))
    assert len(cards) == 2

    c1 = cards[0]
    assert c1.version.value == "3.0"
    assert c1.fn.value == "4567890"
    assert c1.n.value.family == "4567890"
    assert c1.n.value.given == ""
    assert c1.tel.value == "+15551234567"

    c2 = cards[1]
    assert c2.version.value == "3.0"
    assert c2.fn.value == "5678901"
    assert getattr(c2, "tel", None) is None


@pytest.mark.unit
def test_vcf_adversarial_contact_payloads() -> None:
    """Test resilience against malformed, malicious, or unusual contact inputs."""
    adversarial_contacts = [
        # Contact ID with special chars
        ContactInfo(id="123;456", phone="+15551111111"),
        # Contact ID with colons
        ContactInfo(id="user:999", phone="+15552222222"),
        # Contact with Unicode / Persian digits
        ContactInfo(id="۱۲۳۴۵۶۷", phone="+989123456789"),
        # Contact with Emojis
        ContactInfo(id="👤_7777777", phone="+15553333333"),
        # Contact with trailing/leading whitespace
        ContactInfo(id="  9998887  ", phone="  +15554444444  "),
        # Contact with empty phone string
        ContactInfo(id=8881112, phone="   "),
        # Non-string phone (e.g. integer)
        {"id": 7771112, "phone": 15557778888},
        # Duck typed SimpleNamespace
        SimpleNamespace(user_id=6661112, phone="+15556667777"),
        # Contact missing ID (should be skipped gracefully)
        {"phone": "+15550000000"},
        # None contact (should be skipped gracefully)
        None,
        # Contact with ID = 0 (should be treated as string "0")
        {"id": 0, "phone": "+15550000001"},
    ]

    stream = generate_vcf_stream(adversarial_contacts)
    assert stream.tell() == 0

    content = stream.read().decode("utf-8")
    cards = list(vobject.readComponents(content))

    # None and contact missing ID should be safely ignored
    # Total valid cards: 9
    assert len(cards) == 9

    # Check that whitespace was stripped
    fn_values = [c.fn.value for c in cards]
    assert "9998887" in fn_values
    assert "۱۲۳۴۵۶۷" in fn_values


@pytest.mark.unit
def test_vcf_generator_input_types() -> None:
    """Verify generate_vcf_stream handles generator/iterator/empty/None inputs gracefully."""
    # 1. None input
    s1 = generate_vcf_stream(None)
    assert s1.tell() == 0
    assert s1.getvalue() == b""

    # 2. Empty list
    s2 = generate_vcf_stream([])
    assert s2.tell() == 0
    assert s2.getvalue() == b""

    # 3. Generator expression
    gen = (ContactInfo(id=1000 + i) for i in range(10))
    s3 = generate_vcf_stream(gen)
    assert s3.tell() == 0
    assert s3.getvalue().count(b"BEGIN:VCARD") == 10

    # 4. Empty generator
    empty_gen = (c for c in [])
    s4 = generate_vcf_stream(empty_gen)
    assert s4.tell() == 0
    assert s4.getvalue() == b""


# =====================================================================
# CONFIG & SETTINGS ADVERSARIAL TESTS
# =====================================================================

@pytest.mark.unit
def test_settings_rapid_environment_manipulation(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify settings correctly updates under rapid sequential environment mutations."""
    for i in range(30):
        test_id = str(10000 + i)
        test_hash = f"hash_{i:04x}"
        test_token = f"{i}:AAEToken_{i}"

        monkeypatch.setenv("API_ID", test_id)
        monkeypatch.setenv("API_HASH", test_hash)
        monkeypatch.setenv("BOT_TOKEN", test_token)

        s = get_settings(reload=True)
        assert s.api_id == int(test_id)
        assert s.api_hash == test_hash
        assert s.bot_token == test_token


@pytest.mark.unit
@pytest.mark.parametrize("invalid_id", [
    "0",
    "-1",
    "-12345",
    "abc",
    "12.34",
    "123a",
    " 0 ",
    " -5 ",
])
def test_settings_rejects_non_positive_or_malformed_api_id(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, invalid_id: str
) -> None:
    """Verify API_ID rejects zero, negative, floating point, or non-digit strings."""
    monkeypatch.setenv("API_ID", invalid_id)
    monkeypatch.setenv("API_HASH", "valid_hash")
    monkeypatch.setenv("BOT_TOKEN", "123:token")

    with pytest.raises(ValidationError) as exc:
        Settings()
    errs = exc.value.errors()
    assert any(e["loc"][0] == "api_id" for e in errs)


@pytest.mark.unit
def test_settings_rejects_boolean_api_id() -> None:
    """Verify boolean True/False is rejected and not coerced to 1/0."""
    with pytest.raises(ValidationError):
        Settings(api_id=True, api_hash="h", bot_token="t")

    with pytest.raises(ValidationError):
        Settings(api_id=False, api_hash="h", bot_token="t")


@pytest.mark.unit
@pytest.mark.parametrize("field,value", [
    ("api_hash", ""),
    ("api_hash", "   "),
    ("bot_token", ""),
    ("bot_token", "   "),
])
def test_settings_rejects_empty_or_whitespace_secrets(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    """Verify empty or whitespace-only API_HASH and BOT_TOKEN are strictly rejected."""
    monkeypatch.setenv("API_ID", "123456")
    monkeypatch.setenv("API_HASH", "valid_hash")
    monkeypatch.setenv("BOT_TOKEN", "123:valid_token")
    monkeypatch.setenv(field.upper(), value)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.unit
def test_settings_none_string_coercion_observation() -> None:
    """
    Document empirical finding: None passed as api_hash or bot_token is coerced to 'None'
    instead of raising ValidationError, because 'if not isinstance(v, str): v = str(v)'.
    """
    s = Settings(api_id=12345, api_hash=None, bot_token=None)
    assert s.api_hash == "None"
    assert s.bot_token == "None"


@pytest.mark.unit
@pytest.mark.parametrize("invalid_level", [

    "TRACE",
    "VERBOSE",
    "WARN",
    "ALL",
    "",
    "123",
])
def test_settings_log_level_validation(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, invalid_level: str
) -> None:
    """Verify invalid log level values raise ValidationError."""
    monkeypatch.setenv("API_ID", "123456")
    monkeypatch.setenv("API_HASH", "valid_hash")
    monkeypatch.setenv("BOT_TOKEN", "123:token")
    monkeypatch.setenv("LOG_LEVEL", invalid_level)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.unit
def test_settings_ensure_directories_deep_and_idempotent(tmp_path: Path) -> None:
    """Verify ensure_directories creates nested directories and is safely idempotent."""
    deep_sessions = tmp_path / "deep" / "nested" / "path" / "sessions"
    deep_db = tmp_path / "another" / "deep" / "db_dir" / "bot.db"

    s = Settings(
        api_id=123,
        api_hash="h",
        bot_token="t",
        sessions_dir=deep_sessions,
        database_path=deep_db,
    )

    assert not deep_sessions.exists()
    assert not deep_db.parent.exists()

    # Call ensure_directories multiple times to test idempotency
    s.ensure_directories()
    assert deep_sessions.is_dir()
    assert deep_db.parent.is_dir()

    s.ensure_directories()
    assert deep_sessions.is_dir()
    assert deep_db.parent.is_dir()


@pytest.mark.unit
def test_settings_ensure_directories_in_memory() -> None:
    """Verify ensure_directories handles :memory: database path without creating a directory named :memory:."""
    s = Settings(
        api_id=123,
        api_hash="h",
        bot_token="t",
        sessions_dir=Path("tmp_test_sessions"),
        database_path=Path(":memory:"),
    )
    try:
        s.ensure_directories()
        assert not Path(":memory:").exists()
    finally:
        if Path("tmp_test_sessions").exists():
            shutil.rmtree("tmp_test_sessions")


@pytest.mark.unit
def test_settings_concurrent_access() -> None:
    """Verify concurrent thread access to get_settings does not raise exceptions or crash."""
    get_settings(api_id=99999, api_hash="thread_hash", bot_token="thread_token")

    results = []

    def fetch_settings(idx: int) -> int:
        s = get_settings()
        return s.api_id

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_settings, i) for i in range(50)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    assert len(results) == 50
    assert all(r == 99999 for r in results)


if __name__ == "__main__":
    print("Running adversarial test suite standalone...")
    test_vcf_5000_contacts_performance_and_memory()
    test_vcf_10000_contacts_scale_and_tell_zero()
    test_vcf_memory_leak_across_iterations()
    test_vcf_rfc2426_format_compliance()
    test_vcf_adversarial_contact_payloads()
    test_vcf_generator_input_types()
    test_settings_ensure_directories_deep_and_idempotent(Path("temp_stress_test_dir"))
    if Path("temp_stress_test_dir").exists():
        shutil.rmtree("temp_stress_test_dir")
    test_settings_ensure_directories_in_memory()
    test_settings_concurrent_access()
    print("Standalone adversarial verification PASSED successfully!")
