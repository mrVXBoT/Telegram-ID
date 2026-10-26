"""
config.settings
===============
Application configuration and secrets management for Telegram Account Manager.

Loads configuration from environment variables and optional .env file
using Pydantic BaseSettings with strict type validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables and .env file.

    Attributes:
        api_id: Telegram API ID from https://my.telegram.org. Positive integer.
        api_hash: Telegram API Hash from https://my.telegram.org. Non-empty string.
        bot_token: Telegram Bot API Token from @BotFather. Non-empty string.
        sessions_dir: Directory path storing Telethon SQLite session files. Default: 'sessions'.
        database_path: File path for the SQLite database. Default: 'data/bot.db'.
        log_level: Logging verbosity level. Default: 'INFO'.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    api_id: int = Field(
        ...,
        gt=0,
        description="Telegram API ID obtained from https://my.telegram.org",
    )
    api_hash: str = Field(
        ...,
        min_length=1,
        description="Telegram API Hash obtained from https://my.telegram.org",
    )
    bot_token: str = Field(
        ...,
        min_length=1,
        description="Telegram Bot API Token obtained from @BotFather",
    )
    sessions_dir: Path = Field(
        default=Path("sessions"),
        description="Filesystem directory storing Telethon user session files",
    )
    database_path: Path = Field(
        default=Path("data/bot.db"),
        description="Filesystem path for the SQLite database",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging verbosity level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    @field_validator("api_id", mode="before")
    @classmethod
    def validate_api_id(cls, v: Any) -> int:
        """Validate that API_ID is a positive integer."""
        if isinstance(v, bool):
            raise ValueError("API_ID must be an integer, not boolean")
        if isinstance(v, str):
            v = v.strip()
            if not v.isdigit():
                raise ValueError("API_ID must be a positive integer")
            v = int(v)
        if not isinstance(v, int) or v <= 0:
            raise ValueError("API_ID must be a positive integer greater than 0")
        return v

    @field_validator("api_hash", mode="before")
    @classmethod
    def validate_api_hash(cls, v: Any) -> str:
        """Validate that API_HASH is a non-empty string."""
        if not isinstance(v, str):
            v = str(v)
        v = v.strip()
        if not v:
            raise ValueError("API_HASH cannot be empty")
        return v

    @field_validator("bot_token", mode="before")
    @classmethod
    def validate_bot_token(cls, v: Any) -> str:
        """Validate that BOT_TOKEN is a non-empty string."""
        if not isinstance(v, str):
            v = str(v)
        v = v.strip()
        if not v:
            raise ValueError("BOT_TOKEN cannot be empty")
        return v

    @field_validator("sessions_dir", "database_path", mode="before")
    @classmethod
    def validate_paths(cls, v: Any) -> Path:
        """Ensure filesystem paths are converted to Path instances."""
        if isinstance(v, str):
            return Path(v)
        return v

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: Any) -> str:
        """Validate and normalize logging level."""
        val = str(v).strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if val not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(sorted(allowed))}")
        return val

    def ensure_directories(self) -> None:
        """
        Ensure sessions directory and database parent directory exist on disk.
        Safely handles in-memory SQLite paths (':memory:') used in test suites.
        """
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        if str(self.database_path) != ":memory:" and self.database_path.parent != Path("."):
            self.database_path.parent.mkdir(parents=True, exist_ok=True)


_settings_instance: Optional[Settings] = None


def get_settings(reload: bool = False, **kwargs: Any) -> Settings:
    """
    Retrieve the singleton Settings instance.

    Args:
        reload: If True, invalidates cached instance and re-initializes from env/.env.
        **kwargs: Direct field overrides passed to Settings constructor (for testing).

    Returns:
        Settings: Validated application configuration instance.

    Raises:
        pydantic.ValidationError: If required settings are missing or invalid.
    """
    global _settings_instance
    if reload or kwargs or _settings_instance is None:
        _settings_instance = Settings(**kwargs)
    return _settings_instance


def _cache_clear() -> None:
    """Clear cached singleton Settings instance."""
    global _settings_instance
    _settings_instance = None


get_settings.cache_clear = _cache_clear  # type: ignore[attr-defined]
