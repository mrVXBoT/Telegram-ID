"""
tests.conftest
==============
Shared pytest fixtures and test suite configuration.
"""

from __future__ import annotations

import pytest

from config.settings import get_settings


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure environment is devoid of bot settings and clear settings cache."""
    from config.settings import Settings

    # Disable loading from .env file during clean_env tests so local .env files don't leak into tests
    if hasattr(Settings, "model_config") and "env_file" in Settings.model_config:
        monkeypatch.setitem(Settings.model_config, "env_file", None)

    for key in [
        "API_ID",
        "API_HASH",
        "BOT_TOKEN",
        "SESSIONS_DIR",
        "DATABASE_PATH",
        "LOG_LEVEL",
        "api_id",
        "api_hash",
        "bot_token",
        "sessions_dir",
        "database_path",
        "log_level",
    ]:
        monkeypatch.delenv(key, raising=False)

    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    yield
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
