"""
bot.handlers.auth_conversation
==============================
ConversationHandler callbacks and message handlers for account authentication:
- add_account: Prompts for international format phone number.
- phone_handler: Validates phone format, checks authorization, sends SMS code.
- code_handler: Signs in with verification code or initiates 2FA flow.
- password_handler: Verifies two-step verification password.
Features in-place message editing and automatic deletion of sensitive user inputs (phone, SMS, 2FA).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.helpers import send_or_edit_prompt
from bot.keyboards import (
    account_actions_keyboard,
    cancel_auth_keyboard,
    code_cancel_keyboard,
)
from bot.messages import (
    ADD_ACCOUNT_PROMPT,
    INVALID_CODE_TEXT,
    INVALID_PASSWORD_TEXT,
    INVALID_PHONE_TEXT,
    SESSION_EXPIRED_RESTART_TEXT,
    TWO_FA_PROMPT,
    format_already_authorized,
    format_login_success,
    format_verification_prompt,
)
from bot.states import ACCOUNT_ACTIONS, CODE, PHONE, WAITING_FOR_CODE
from services.auth_service import AuthService
from services.session_manager import TelethonSessionManager
from utils.phone import validate_phone_number

logger = logging.getLogger(__name__)


def _get_services(context: ContextTypes.DEFAULT_TYPE) -> tuple[TelethonSessionManager, AuthService]:
    """Retrieve or lazily construct session manager and auth service."""
    sm = context.bot_data.get("session_manager")
    if sm is None:
        sm = TelethonSessionManager()
        context.bot_data["session_manager"] = sm

    auth = context.bot_data.get("auth_service")
    if auth is None:
        auth = AuthService(sm)
        context.bot_data["auth_service"] = auth

    return sm, auth


async def add_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: prompts user for phone number to link a new Telegram account in-place."""
    reply_markup = cancel_auth_keyboard()
    await send_or_edit_prompt(
        update=update,
        context=context,
        text=ADD_ACCOUNT_PROMPT,
        reply_markup=reply_markup,
        delete_user_msg=True,
    )
    return PHONE


async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process submitted phone number, validate format, and initiate Telegram login."""
    if not update.message or not update.message.text:
        return PHONE

    raw_phone = update.message.text.strip()
    user = update.effective_user
    user_id = user.id if user else 0

    sanitized_phone = validate_phone_number(raw_phone)
    if not sanitized_phone:
        await send_or_edit_prompt(
            update=update,
            context=context,
            text=INVALID_PHONE_TEXT,
            reply_markup=None,
            delete_user_msg=True,
        )
        return PHONE

    context.user_data["phone"] = sanitized_phone
    session_manager, auth_service = _get_services(context)

    try:
        if await session_manager.is_authorized(sanitized_phone):
            # Account already has a valid authorized session
            account_repo = context.bot_data.get("account_repo")
            if account_repo is not None:
                await account_repo.add_account(
                    user_id=user_id,
                    phone=sanitized_phone,
                    status="active",
                    auto_create_user=True,
                )

            reply_markup = account_actions_keyboard(sanitized_phone)
            await send_or_edit_prompt(
                update=update,
                context=context,
                text=format_already_authorized(sanitized_phone),
                reply_markup=reply_markup,
                delete_user_msg=True,
            )
            context.user_data["current_phone"] = sanitized_phone
            return ConversationHandler.END

        # Request verification code via Telethon
        phone_code_hash = await auth_service.send_code(sanitized_phone)
        client = await session_manager.get_client(sanitized_phone)

        pending: Dict[int, Dict[str, Any]] = context.bot_data.setdefault("pending_auth", {})
        pending[user_id] = {
            "phone": sanitized_phone,
            "client": client,
            "phone_code_hash": phone_code_hash,
        }

        reply_markup = code_cancel_keyboard()
        await send_or_edit_prompt(
            update=update,
            context=context,
            text=format_verification_prompt(sanitized_phone),
            reply_markup=reply_markup,
            delete_user_msg=True,
        )
        return CODE

    except Exception as e:
        logger.error("Error in phone handler for %s: %s", sanitized_phone, e)
        error_msg = f"❌ خطا: {str(e)}\nError: {str(e)}\nPlease try again with a valid phone number."
        await send_or_edit_prompt(
            update=update,
            context=context,
            text=error_msg,
            reply_markup=None,
            delete_user_msg=True,
        )
        return ConversationHandler.END


async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process verification code input, completing login or routing to 2FA."""
    if not update.message or not update.message.text:
        return CODE

    user = update.effective_user
    user_id = user.id if user else 0
    pending: Dict[int, Dict[str, Any]] = context.bot_data.setdefault("pending_auth", {})

    if user_id not in pending:
        await send_or_edit_prompt(
            update=update,
            context=context,
            text=SESSION_EXPIRED_RESTART_TEXT,
            reply_markup=None,
            delete_user_msg=True,
        )
        return ConversationHandler.END

    raw_code = update.message.text.strip()
    clean_code = re.sub(r"[\s-]", "", raw_code)

    auth_info = pending[user_id]
    phone = auth_info["phone"]
    phone_code_hash = auth_info.get("phone_code_hash")

    session_manager, auth_service = _get_services(context)

    try:
        result = await auth_service.sign_in(
            phone=phone,
            code=clean_code,
            phone_code_hash=phone_code_hash,
        )

        if result.is_success:
            account_repo = context.bot_data.get("account_repo")
            if account_repo is not None:
                await account_repo.add_account(
                    user_id=user_id,
                    phone=phone,
                    status="active",
                    auto_create_user=True,
                )

            pending.pop(user_id, None)
            context.user_data["current_phone"] = phone

            reply_markup = account_actions_keyboard(phone)
            await send_or_edit_prompt(
                update=update,
                context=context,
                text=format_login_success(phone),
                reply_markup=reply_markup,
                delete_user_msg=True,
            )
            return ACCOUNT_ACTIONS

        if result.requires_2fa:
            context.user_data["awaiting_2fa"] = True
            await send_or_edit_prompt(
                update=update,
                context=context,
                text=TWO_FA_PROMPT,
                reply_markup=None,
                delete_user_msg=True,
            )
            return WAITING_FOR_CODE

        if result.status == "invalid_code":
            await send_or_edit_prompt(
                update=update,
                context=context,
                text=INVALID_CODE_TEXT,
                reply_markup=None,
                delete_user_msg=True,
            )
            return CODE

        # Other auth failures (expired code, banned, flood wait)
        err_msg = result.message or "Authentication failed."
        await send_or_edit_prompt(
            update=update,
            context=context,
            text=f"❌ خطا: {err_msg}\nError: {err_msg}",
            reply_markup=None,
            delete_user_msg=True,
        )
        await session_manager.disconnect(phone)
        pending.pop(user_id, None)
        return ConversationHandler.END

    except Exception as e:
        logger.error("Unexpected error in code handler for %s: %s", phone, e)
        await send_or_edit_prompt(
            update=update,
            context=context,
            text=f"❌ خطا: {str(e)}\nError: {str(e)}",
            reply_markup=None,
            delete_user_msg=True,
        )
        await session_manager.disconnect(phone)
        pending.pop(user_id, None)
        return ConversationHandler.END


async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process two-step verification password input."""
    if not update.message or not update.message.text:
        return WAITING_FOR_CODE

    user = update.effective_user
    user_id = user.id if user else 0
    pending: Dict[int, Dict[str, Any]] = context.bot_data.setdefault("pending_auth", {})

    if user_id not in pending:
        await send_or_edit_prompt(
            update=update,
            context=context,
            text=SESSION_EXPIRED_RESTART_TEXT,
            reply_markup=None,
            delete_user_msg=True,
        )
        return ConversationHandler.END

    password = update.message.text.strip()
    auth_info = pending[user_id]
    phone = auth_info["phone"]

    session_manager, auth_service = _get_services(context)

    try:
        result = await auth_service.sign_in_2fa(phone=phone, password=password)

        if result.is_success:
            account_repo = context.bot_data.get("account_repo")
            if account_repo is not None:
                await account_repo.add_account(
                    user_id=user_id,
                    phone=phone,
                    status="active",
                    auto_create_user=True,
                )

            pending.pop(user_id, None)
            context.user_data["current_phone"] = phone

            reply_markup = account_actions_keyboard(phone)
            await send_or_edit_prompt(
                update=update,
                context=context,
                text=format_login_success(phone),
                reply_markup=reply_markup,
                delete_user_msg=True,
            )
            return ACCOUNT_ACTIONS

        if result.status == "invalid_password":
            await send_or_edit_prompt(
                update=update,
                context=context,
                text=INVALID_PASSWORD_TEXT,
                reply_markup=None,
                delete_user_msg=True,
            )
            return WAITING_FOR_CODE

        err_msg = result.message or "2FA authentication failed."
        await send_or_edit_prompt(
            update=update,
            context=context,
            text=f"❌ خطا: {err_msg}\nError: {err_msg}",
            reply_markup=None,
            delete_user_msg=True,
        )
        await session_manager.disconnect(phone)
        pending.pop(user_id, None)
        return ConversationHandler.END

    except Exception as e:
        logger.error("Unexpected error in password handler for %s: %s", phone, e)
        await send_or_edit_prompt(
            update=update,
            context=context,
            text=f"❌ خطا: {str(e)}\nError: {str(e)}",
            reply_markup=None,
            delete_user_msg=True,
        )
        await session_manager.disconnect(phone)
        pending.pop(user_id, None)
        return ConversationHandler.END
