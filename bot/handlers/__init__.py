"""
bot.handlers
============
Package aggregating all bot commands, callback query routers, and message handlers.
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.handlers.account_menu import (
    list_accounts_callback,
    logout_account_callback,
    select_account_callback,
)
from bot.handlers.auth_conversation import (
    add_account_callback,
    code_handler,
    password_handler,
    phone_handler,
)
from bot.handlers.chat_handlers import (
    get_code_callback,
    list_chats_callback,
)
from bot.handlers.contact_handlers import (
    check_contacts_callback,
    confirm_delete_callback,
    delete_contacts_callback,
    export_mutual_callback,
    extract_contacts_callback,
)
from bot.handlers.start import (
    back_to_menu,
    cancel,
    cancel_auth,
    default_message_handler,
    error_handler,
    help_guide_callback,
    start,
)

logger = logging.getLogger(__name__)


async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Central dispatcher routing callback queries to their dedicated modular handlers.
    Matches 100% of callback signals defined in TG-ID.py and Explorer Survey 1.
    """
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    data = query.data or ""
    logger.debug("Routing callback query: %s", data)

    # Core Navigation & Cancellation
    if data == "cancel_auth":
        return await cancel_auth(update, context)

    if data == "back_to_menu":
        return await back_to_menu(update, context)

    if data == "help_guide":
        return await help_guide_callback(update, context)

    # Account Management
    if data == "add_account":
        return await add_account_callback(update, context)

    if data == "list_accounts":
        return await list_accounts_callback(update, context)

    if data.startswith("select_"):
        return await select_account_callback(update, context)

    if data.startswith("logout_"):
        return await logout_account_callback(update, context)

    # Contact Operations
    if data.startswith("check_contacts_"):
        return await check_contacts_callback(update, context)

    if data.startswith("extract_"):
        return await extract_contacts_callback(update, context)

    if data.startswith("export_mutual_"):
        return await export_mutual_callback(update, context)

    if data.startswith("delete_contacts_"):
        return await delete_contacts_callback(update, context)

    if data.startswith("confirm_delete_"):
        return await confirm_delete_callback(update, context)

    # Chats & Auth Code Operations
    if data.startswith("list_chats_"):
        return await list_chats_callback(update, context)

    if data.startswith("get_code_"):
        return await get_code_callback(update, context)

    # Unrecognized callback data
    await query.answer()
    return ConversationHandler.END


__all__ = [
    "start",
    "cancel",
    "cancel_auth",
    "back_to_menu",
    "default_message_handler",
    "error_handler",
    "add_account_callback",
    "phone_handler",
    "code_handler",
    "password_handler",
    "list_accounts_callback",
    "select_account_callback",
    "logout_account_callback",
    "check_contacts_callback",
    "extract_contacts_callback",
    "export_mutual_callback",
    "delete_contacts_callback",
    "confirm_delete_callback",
    "list_chats_callback",
    "get_code_callback",
    "button_router",
]
