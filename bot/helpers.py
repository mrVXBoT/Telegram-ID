"""
bot.helpers
===========
Utility functions for clean, in-place message editing, safe user message deletion,
and prompt tracking to ensure zero chat clutter.
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import InlineKeyboardMarkup, Message, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def delete_user_message_safe(update: Update) -> bool:
    """
    Safely delete the user's incoming message (text, command, or media).
    Prevents sensitive data (phone, SMS code, passwords) from lingering in chat.
    Silently catches any errors if deletion is not permitted.
    """
    if not update or not update.message:
        return False
    try:
        await update.message.delete()
        return True
    except TelegramError as e:
        logger.debug("Failed to delete user message: %s", e)
        return False
    except Exception as e:
        logger.debug("Unexpected exception deleting user message: %s", e)
        return False


async def send_or_edit_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    delete_user_msg: bool = True,
) -> Optional[Message]:
    """
    Maintain a single living prompt message in the chat:
    1. If triggered by a callback query, edits the callback query's message directly.
    2. If triggered by a user message and delete_user_msg=True, deletes the user message.
    3. If prompt_message_id is tracked in context.user_data, edits that message.
    4. If no prompt_message_id exists or edit fails, replies with update.message.reply_text
       or context.bot.send_message and tracks the new prompt_message_id.
    """
    # 1. If triggered by callback query, edit in-place
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass

        try:
            edited = await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
            )
            if hasattr(edited, "message_id"):
                context.user_data["prompt_message_id"] = edited.message_id
            return edited  # type: ignore[return-value]
        except TelegramError as e:
            if "Message is not modified" in str(e):
                return update.callback_query.message  # type: ignore[return-value]
            logger.debug("callback_query edit failed: %s, falling back", e)

    # 2. If triggered by user message, safely delete user's message
    if update.message and delete_user_msg:
        await delete_user_message_safe(update)

    chat_id = update.effective_chat.id if update.effective_chat else 0
    prompt_msg_id = context.user_data.get("prompt_message_id")

    # 3. Attempt editing the existing tracked prompt message
    if chat_id and prompt_msg_id and context.bot:
        try:
            edited = await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=prompt_msg_id,
                text=text,
                reply_markup=reply_markup,
            )
            return edited  # type: ignore[return-value]
        except TelegramError as e:
            if "Message is not modified" in str(e):
                return None
            logger.debug("Failed to edit tracked prompt %s: %s", prompt_msg_id, e)
        except Exception as e:
            logger.debug("Exception editing prompt %s: %s", prompt_msg_id, e)

    # 4. Fallback: reply to message if available (maintains mock test compatibility)
    if update.message and hasattr(update.message, "reply_text"):
        try:
            if reply_markup is not None:
                msg = await update.message.reply_text(
                    text=text,
                    reply_markup=reply_markup,
                )
            else:
                msg = await update.message.reply_text(text)
            if hasattr(msg, "message_id"):
                context.user_data["prompt_message_id"] = msg.message_id
            return msg
        except Exception as e:
            logger.debug("reply_text fallback failed: %s", e)

    # 5. Fallback: context.bot.send_message
    if chat_id and context.bot:
        try:
            if reply_markup is not None:
                new_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                )
            else:
                new_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                )
            if hasattr(new_msg, "message_id"):
                context.user_data["prompt_message_id"] = new_msg.message_id
            return new_msg
        except Exception as e:
            logger.error("Failed to send prompt message: %s", e)

    return None
