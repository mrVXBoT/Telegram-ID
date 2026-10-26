"""
main.py
=======
Bootstrap entry point for the Telegram Account Manager & Contact Extractor Bot.
Loads validated configuration, configures logging, builds the PTB Application,
and starts polling.
"""

from __future__ import annotations

import logging
import sys

from bot.application import build_application
from config.settings import get_settings

logger = logging.getLogger("main")


def main() -> None:
    """Bootstrap and start the Telegram bot application."""
    try:
        settings = get_settings()
    except Exception as e:
        sys.stderr.write(f"Configuration error: {e}\n")
        sys.exit(1)

    log_level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=log_level,
    )

    settings.ensure_directories()
    logger.info("Initializing Telegram Account Manager Bot...")
    logger.info("Database path: %s | Sessions directory: %s", settings.database_path, settings.sessions_dir)

    app = build_application(settings=settings)

    logger.info("Starting bot polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
