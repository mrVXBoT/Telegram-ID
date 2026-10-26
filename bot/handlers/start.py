"""
bot.handlers.start
==================
Command and core navigation handlers:
- /start: Welcomes the user, initializes user record, resets pending auth, edits in-place.
- /cancel & cancel_auth: Aborts current operation, releases pending clients, returns to menu.
- back_to_menu: Navigates back to the main menu from sub-menus.
- default_message_handler: Fallback for unmatched text messages.
- error_handler: Centralized error handling and logging.
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.helpers import delete_user_message_safe
from bot.keyboards import main_menu_keyboard
from bot.messages import (
    DEFAULT_FALLBACK_TEXT,
    ERROR_GENERIC_TEXT,
    ERROR_SUPPORT_TEXT,
    OPERATION_CANCELLED_TEXT,
    format_welcome,
)

logger = logging.getLogger(__name__)


async def cleanup_pending_auth(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disconnect and remove any pending Telethon client for this user."""
    pending = context.bot_data.setdefault("pending_auth", {})
    entry = pending.pop(user_id, None)
    if entry and isinstance(entry, dict):
        client = entry.get("client")
        if client and hasattr(client, "disconnect"):
            try:
                await client.disconnect()
            except Exception as e:
                logger.debug("Error disconnecting pending client for %s: %s", user_id, e)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send welcome message or edit existing prompt when /start is issued."""
    try:
        user = update.effective_user
        user_id = user.id if user else 0
        if user_id:
            await cleanup_pending_auth(user_id, context)

            user_repo = context.bot_data.get("user_repo")
            if user_repo is not None:
                try:
                    await user_repo.get_or_create_user(user_id)
                except Exception as db_err:
                    logger.warning("Could not record user %s in database: %s", user_id, db_err)

        reply_markup = main_menu_keyboard()
        chat_id = (
            update.effective_chat.id
            if update.effective_chat
            else (user.id if user else 0)
        )

        prompt_msg_id = context.user_data.get("prompt_message_id")
        if update.callback_query:
            await update.callback_query.answer()
            edited = await update.callback_query.edit_message_text(
                text=format_welcome(),
                reply_markup=reply_markup,
            )
            if hasattr(edited, "message_id"):
                context.user_data["prompt_message_id"] = edited.message_id
        elif chat_id and prompt_msg_id and context.bot:
            await delete_user_message_safe(update)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=prompt_msg_id,
                    text=format_welcome(),
                    reply_markup=reply_markup,
                )
            except Exception:
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=format_welcome(),
                    reply_markup=reply_markup,
                )
                if hasattr(msg, "message_id"):
                    context.user_data["prompt_message_id"] = msg.message_id
        elif chat_id and context.bot:
            await delete_user_message_safe(update)
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=format_welcome(),
                reply_markup=reply_markup,
            )
            if hasattr(msg, "message_id"):
                context.user_data["prompt_message_id"] = msg.message_id

        logger.info("Start command processed for user %s", user_id)
    except Exception as e:
        logger.error("Error in start command: %s", e)
        if update.effective_chat and context.bot:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=ERROR_GENERIC_TEXT,
            )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel any active conversation and return to main menu in-place."""
    user = update.effective_user
    if user:
        await cleanup_pending_auth(user.id, context)

    reply_markup = main_menu_keyboard()

    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                text=OPERATION_CANCELLED_TEXT,
                reply_markup=reply_markup,
            )
        except Exception:
            if update.effective_chat and context.bot:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=OPERATION_CANCELLED_TEXT,
                    reply_markup=reply_markup,
                )
    elif update.message:
        await delete_user_message_safe(update)
        prompt_msg_id = context.user_data.get("prompt_message_id")
        chat_id = update.effective_chat.id if update.effective_chat else 0
        edited = False
        if prompt_msg_id and chat_id and context.bot:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=prompt_msg_id,
                    text=OPERATION_CANCELLED_TEXT,
                    reply_markup=reply_markup,
                )
                edited = True
            except Exception:
                pass
        if not edited:
            await update.message.reply_text(
                text=OPERATION_CANCELLED_TEXT,
                reply_markup=reply_markup,
            )
    return ConversationHandler.END


async def cancel_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback query handler for cancel_auth buttons."""
    return await cancel(update, context)


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Return to main menu from account list or other sub-menus in-place."""
    if update.callback_query:
        await update.callback_query.answer()
        reply_markup = main_menu_keyboard()
        await update.callback_query.edit_message_text(
            text=format_welcome(),
            reply_markup=reply_markup,
        )
    return ConversationHandler.END


async def help_guide_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Display comprehensive feature guide and documentation in-place."""
    if update.callback_query:
        await update.callback_query.answer()
        from bot.keyboards import help_guide_keyboard
        from bot.messages import HELP_GUIDE_TEXT

        reply_markup = help_guide_keyboard()
        await update.callback_query.edit_message_text(
            text=HELP_GUIDE_TEXT,
            reply_markup=reply_markup,
        )
    return ConversationHandler.END


async def default_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Fallback handler for unhandled non-command text messages."""
    if update.message:
        await delete_user_message_safe(update)
        prompt_msg_id = context.user_data.get("prompt_message_id")
        chat_id = update.effective_chat.id if update.effective_chat else 0
        reply_markup = main_menu_keyboard()
        edited = False
        if prompt_msg_id and chat_id and context.bot:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=prompt_msg_id,
                    text=DEFAULT_FALLBACK_TEXT,
                    reply_markup=reply_markup,
                )
                edited = True
            except Exception:
                pass
        if not edited:
            await update.message.reply_text(
                text=DEFAULT_FALLBACK_TEXT,
                reply_markup=reply_markup,
            )


async def error_handler(
    update: Optional[object], context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Global error handler logging exceptions and notifying the user."""
    logger.error("Exception handling update %s: %s", update, context.error)
    try:
        chat = getattr(update, "effective_chat", None)
        if chat and hasattr(chat, "id") and chat.id and context.bot:
            await context.bot.send_message(
                chat_id=chat.id,
                text=ERROR_SUPPORT_TEXT,
            )
    except Exception as e:
        logger.error("Failed to deliver error notification to chat: %s", e)
