"""
Unit tests for config/settings.py.

Verifies:
- Environment variable loading
- Sensible default paths (sessions_dir, database_path)
- Custom path overrides
- Direct kwargs initialization
- get_settings singleton caching and cache_clear
- Validation error handling for missing/empty/invalid credentials
- Case-insensitivity and ignoring extra environment variables
"""

from __future__ import annotations

from pathlib import Path
import pytest
from pydantic import ValidationError

from config.settings import Settings, get_settings


@pytest.mark.unit
def test_settings_load_from_environment(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify loading required settings directly from environment variables."""
    monkeypatch.setenv("API_ID", "16208243")
    monkeypatch.setenv("API_HASH", "a72ed8b5f6475a644c61f54ff367c1f6")
    monkeypatch.setenv("BOT_TOKEN", "8619968352:AAEFW0ui0QkXX9SKzPztPSzzzN7nourBxo4")

    s = get_settings()
    assert s.api_id == 16208243
    assert isinstance(s.api_id, int)
    assert s.api_hash == "a72ed8b5f6475a644c61f54ff367c1f6"
    assert s.bot_token == "8619968352:AAEFW0ui0QkXX9SKzPztPSzzzN7nourBxo4"


@pytest.mark.unit
def test_settings_default_sessions_dir(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify default sessions_dir path is Path('sessions')."""
    monkeypatch.setenv("API_ID", "123456")
    monkeypatch.setenv("API_HASH", "hash123")
    monkeypatch.setenv("BOT_TOKEN", "123:token")

    s = get_settings()
    assert s.sessions_dir == Path("sessions")
    assert isinstance(s.sessions_dir, Path)


@pytest.mark.unit
def test_settings_default_database_path(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify default database_path is Path('data/bot.db')."""
    monkeypatch.setenv("API_ID", "123456")
    monkeypatch.setenv("API_HASH", "hash123")
    monkeypatch.setenv("BOT_TOKEN", "123:token")

    s = get_settings()
    assert s.database_path == Path("data/bot.db")
    assert isinstance(s.database_path, Path)


@pytest.mark.unit
def test_settings_custom_paths_from_env(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify custom SESSIONS_DIR and DATABASE_PATH are parsed into Path instances."""
    monkeypatch.setenv("API_ID", "123456")
    monkeypatch.setenv("API_HASH", "hash123")
    monkeypatch.setenv("BOT_TOKEN", "123:token")
    monkeypatch.setenv("SESSIONS_DIR", "custom_sess")
    monkeypatch.setenv("DATABASE_PATH", "custom_data/custom.db")

    s = get_settings()
    assert s.sessions_dir == Path("custom_sess")
    assert s.database_path == Path("custom_data/custom.db")


@pytest.mark.unit
def test_settings_direct_kwargs_initialization() -> None:
    """Verify initializing Settings via direct keyword arguments."""
    s = Settings(
        api_id=123,
        api_hash="h",
        bot_token="b",
        sessions_dir=Path("s"),
        database_path=Path("d"),
    )
    assert s.api_id == 123
    assert s.api_hash == "h"
    assert s.bot_token == "b"
    assert s.sessions_dir == Path("s")
    assert s.database_path == Path("d")


@pytest.mark.unit
def test_get_settings_caching(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify get_settings returns cached singleton on repeated calls."""
    monkeypatch.setenv("API_ID", "123456")
    monkeypatch.setenv("API_HASH", "hash123")
    monkeypatch.setenv("BOT_TOKEN", "123:token")

    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


@pytest.mark.unit
def test_settings_missing_all_required_keys(clean_env: None) -> None:
    """Verify ValidationError is raised with all 3 missing fields when unconfigured."""
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    errors = exc_info.value.errors()
    missing_fields = {e["loc"][0] for e in errors}
    assert "api_id" in missing_fields
    assert "api_hash" in missing_fields
    assert "bot_token" in missing_fields


@pytest.mark.unit
@pytest.mark.parametrize("missing_key", ["API_ID", "API_HASH", "BOT_TOKEN"])
def test_settings_missing_single_required_key(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, missing_key: str
) -> None:
    """Verify omitting any single required credential raises ValidationError for that key."""
    all_keys = {
        "API_ID": "123456",
        "API_HASH": "hash123",
        "BOT_TOKEN": "123:token",
    }
    for k, v in all_keys.items():
        if k != missing_key:
            monkeypatch.setenv(k, v)

    with pytest.raises(ValidationError) as exc_info:
        Settings()
    errors = exc_info.value.errors()
    missing_fields = {e["loc"][0] for e in errors}
    assert missing_key.lower() in missing_fields


@pytest.mark.unit
def test_settings_invalid_api_id_type(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify non-numeric string for API_ID raises ValidationError."""
    monkeypatch.setenv("API_ID", "not_a_number")
    monkeypatch.setenv("API_HASH", "hash123")
    monkeypatch.setenv("BOT_TOKEN", "123:token")

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.unit
@pytest.mark.parametrize("key", ["API_HASH", "BOT_TOKEN"])
def test_settings_empty_secrets_validation(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    """Verify empty secret string raises ValidationError."""
    monkeypatch.setenv("API_ID", "123456")
    monkeypatch.setenv("API_HASH", "valid_hash")
    monkeypatch.setenv("BOT_TOKEN", "valid:token")
    monkeypatch.setenv(key, "")

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.unit
def test_settings_extra_env_vars_ignored(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify unrecognized environment variables are ignored without error."""
    monkeypatch.setenv("API_ID", "123")
    monkeypatch.setenv("API_HASH", "hash")
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("EXTRA_VAR", "unexpected")

    s = Settings()
    assert s.api_id == 123


@pytest.mark.unit
def test_settings_case_insensitive_env(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify lowercase environment variable names are correctly bound."""
    monkeypatch.setenv("api_id", "123")
    monkeypatch.setenv("api_hash", "h")
    monkeypatch.setenv("bot_token", "b")

    s = Settings()
    assert s.api_id == 123
    assert s.api_hash == "h"
    assert s.bot_token == "b"
