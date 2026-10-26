"""
bot.handlers.chat_handlers
==========================
Handlers for listing creator chats/channels with visibility and creation dates,
and retrieving the latest Telegram login authentication code (peer 777000).
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards import account_actions_keyboard, back_to_actions_keyboard
from bot.messages import (
    CODE_ERROR_TEXT,
    format_bilingual_error,
    format_creator_chats,
    format_latest_code,
    format_no_code_found,
)
from bot.states import ACCOUNT_ACTIONS
from services.chat_service import ChatService
from services.session_manager import TelethonSessionManager

logger = logging.getLogger(__name__)


def _get_chat_service(context: ContextTypes.DEFAULT_TYPE) -> ChatService:
    cs = context.bot_data.get("chat_service")
    if cs is None:
        sm = context.bot_data.get("session_manager")
        if sm is None:
            sm = TelethonSessionManager()
            context.bot_data["session_manager"] = sm
        cs = ChatService(sm)
        context.bot_data["chat_service"] = cs
    return cs


async def list_chats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Retrieve user-created channels, groups, and chats and display formatted inventory."""
    query = update.callback_query
    if not query or not query.data:
        return ACCOUNT_ACTIONS

    await query.answer()
    phone = query.data.replace("list_chats_", "").strip()

    try:
        chat_service = _get_chat_service(context)
        chats = await chat_service.list_creator_chats(phone)

        text = format_creator_chats(phone, chats)
        reply_markup = back_to_actions_keyboard(phone)
        await query.edit_message_text(text=text, reply_markup=reply_markup)
        return ACCOUNT_ACTIONS

    except Exception as e:
        logger.error("Error listing creator chats for %s: %s", phone, e)
        reply_markup = back_to_actions_keyboard(phone)
        error_notice = format_bilingual_error(
            title_fa="دریافت لیست چت‌ها",
            title_en="Listing creator chats",
            error=str(e),
        )
        await query.edit_message_text(
            text=f"{error_notice}\nError listing chats: {str(e)}",
            reply_markup=reply_markup,
        )
        return ACCOUNT_ACTIONS


async def get_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Retrieve the latest 5-digit verification code from Telegram official peer 777000."""
    query = update.callback_query
    if not query or not query.data:
        return ACCOUNT_ACTIONS

    await query.answer()
    phone = query.data.replace("get_code_", "").strip()

    try:
        chat_service = _get_chat_service(context)
        code_message = await chat_service.get_latest_login_message(phone)

        if code_message:
            text = format_latest_code(phone, code_message)
        else:
            text = format_no_code_found(phone)

        reply_markup = account_actions_keyboard(phone)
        await query.edit_message_text(text=text, reply_markup=reply_markup)
        return ACCOUNT_ACTIONS

    except Exception as e:
        logger.error("Error retrieving login code for %s: %s", phone, e)
        reply_markup = account_actions_keyboard(phone)
        await query.edit_message_text(
            text=CODE_ERROR_TEXT.format(error=str(e)),
            reply_markup=reply_markup,
        )
        return ACCOUNT_ACTIONS
