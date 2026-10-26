"""
bot.application
===============
Factory for constructing and configuring the python-telegram-bot Application
with dependency lifecycle hooks, database initialization, auto-migration,
and conversation state management.
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.handlers import (
    button_router,
    code_handler,
    default_message_handler,
    error_handler,
    password_handler,
    phone_handler,
    start,
    cancel,
)
from bot.states import ACCOUNT_ACTIONS, CODE, PHONE, WAITING_FOR_CODE
from config.settings import Settings, get_settings
from database.connection import DatabaseConnection
from database.migration import auto_migrate
from database.repository import (
    AccountRepository,
    MetadataRepository,
    OperationLogRepository,
    UserRepository,
)
from services.auth_service import AuthService
from services.chat_service import ChatService
from services.contact_service import ContactService
from services.session_manager import TelethonSessionManager

logger = logging.getLogger(__name__)


def create_conversation_handler() -> ConversationHandler:
    """
    Construct the unified ConversationHandler with allow_reentry=True
    and full state transitions matching TG-ID.py specifications.
    """
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_router),
        ],
        states={
            PHONE: [
                CommandHandler("start", start),
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(button_router),
                MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler),
            ],
            CODE: [
                CommandHandler("start", start),
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(button_router),
                MessageHandler(filters.TEXT & ~filters.COMMAND, code_handler),
            ],
            WAITING_FOR_CODE: [
                CommandHandler("start", start),
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(button_router),
                MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler),
            ],
            ACCOUNT_ACTIONS: [
                CommandHandler("start", start),
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(button_router),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
            CallbackQueryHandler(button_router),
        ],
        allow_reentry=True,
        per_message=False,
    )


def build_application(
    settings: Optional[Settings] = None,
    db_conn: Optional[DatabaseConnection] = None,
    session_manager: Optional[TelethonSessionManager] = None,
) -> Application:
    """
    Assemble and configure the python-telegram-bot Application.

    Args:
        settings: Optional Settings instance. Falls back to get_settings().
        db_conn: Optional DatabaseConnection instance.
        session_manager: Optional TelethonSessionManager instance.

    Returns:
        Configured Application instance with lifecycle hooks and handlers.
    """
    resolved_settings = settings or get_settings()
    resolved_settings.ensure_directories()

    resolved_db = db_conn or DatabaseConnection(resolved_settings.database_path)
    resolved_sm = session_manager or TelethonSessionManager(settings=resolved_settings)

    # Initialize repository instances
    user_repo = UserRepository(resolved_db)
    account_repo = AccountRepository(resolved_db)
    op_repo = OperationLogRepository(resolved_db)
    meta_repo = MetadataRepository(resolved_db)

    # Initialize service instances
    auth_service = AuthService(resolved_sm)
    contact_service = ContactService(resolved_sm)
    chat_service = ChatService(resolved_sm)

    async def post_init(app: Application) -> None:
        """Lifecycle hook executed after event loop starts, before polling begins."""
        logger.info("Running post_init lifecycle hook: initializing database and running migration")
        await resolved_db.init_db()
        try:
            meta_repo = MetadataRepository(resolved_db)
            migrated = await meta_repo.get("json_migration_completed")
            if migrated:
                logger.info("JSON migration already completed. Skipping auto_migrate.")
            else:
                migration_res = await auto_migrate(
                    db_conn=resolved_db,
                    sessions_dir=resolved_settings.sessions_dir,
                )
                logger.info("Auto-migration status: %s", migration_res.details)
        except Exception as e:
            logger.warning("Auto-migration encounter error (non-fatal): %s", e)

    async def post_shutdown(app: Application) -> None:
        """Lifecycle hook executed on application termination for safe cleanup."""
        logger.info("Running post_shutdown lifecycle hook: disconnecting Telethon clients and closing DB")
        try:
            await resolved_sm.disconnect_all()
        except Exception as e:
            logger.warning("Error during session manager shutdown: %s", e)
        try:
            await resolved_db.close()
        except Exception as e:
            logger.warning("Error during database close: %s", e)

    # Build Application with hooks
    builder = ApplicationBuilder().token(resolved_settings.bot_token)
    builder.post_init(post_init)
    builder.post_shutdown(post_shutdown)
    application = builder.build()

    # Store shared services in bot_data for decoupled handler access
    application.bot_data["settings"] = resolved_settings
    application.bot_data["db"] = resolved_db
    application.bot_data["session_manager"] = resolved_sm
    application.bot_data["user_repo"] = user_repo
    application.bot_data["account_repo"] = account_repo
    application.bot_data["op_repo"] = op_repo
    application.bot_data["meta_repo"] = meta_repo
    application.bot_data["auth_service"] = auth_service
    application.bot_data["contact_service"] = contact_service
    application.bot_data["chat_service"] = chat_service
    application.bot_data["pending_auth"] = {}

    # Register handlers
    conv_handler = create_conversation_handler()
    application.add_handler(conv_handler)
    application.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, default_message_handler)
    )
    application.add_error_handler(error_handler)

    return application
