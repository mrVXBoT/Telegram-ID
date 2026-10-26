"""
bot.handlers.account_menu
=========================
Handlers for account listing, account selection, and account logout.
Supports in-place editing and bilingual error handling.
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.helpers import send_or_edit_prompt
from bot.keyboards import (
    account_actions_keyboard,
    account_list_keyboard,
    back_to_accounts_keyboard,
)
from bot.messages import (
    ACCOUNT_NOT_FOUND_TEXT,
    NO_ACCOUNTS_TEXT,
    SESSION_EXPIRED_TEXT,
    format_account_actions,
    format_accounts_list,
    format_bilingual_error,
    format_logout_success,
)
from bot.states import ACCOUNT_ACTIONS
from database.repository import AccountRepository, OperationLogRepository
from services.auth_service import AuthService
from services.session_manager import TelethonSessionManager

logger = logging.getLogger(__name__)


def _get_account_repo(context: ContextTypes.DEFAULT_TYPE) -> Optional[AccountRepository]:
    return context.bot_data.get("account_repo")


def _get_session_manager(context: ContextTypes.DEFAULT_TYPE) -> TelethonSessionManager:
    sm = context.bot_data.get("session_manager")
    if sm is None:
        sm = TelethonSessionManager()
        context.bot_data["session_manager"] = sm
    return sm


def _get_auth_service(context: ContextTypes.DEFAULT_TYPE) -> AuthService:
    auth = context.bot_data.get("auth_service")
    if auth is None:
        sm = _get_session_manager(context)
        auth = AuthService(sm)
        context.bot_data["auth_service"] = auth
    return auth


async def list_accounts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Display all linked accounts owned by the user, or prompt to add one if empty (in-place)."""
    user = update.effective_user
    user_id = user.id if user else 0
    account_repo = _get_account_repo(context)

    accounts = []
    if account_repo is not None and user_id:
        try:
            accounts = await account_repo.get_user_accounts(user_id)
        except Exception as e:
            logger.error("Error retrieving accounts for user %s: %s", user_id, e)

    phones = [a.phone_number for a in accounts]
    reply_markup = account_list_keyboard(phones)
    text = format_accounts_list(phones)

    await send_or_edit_prompt(
        update=update,
        context=context,
        text=text,
        reply_markup=reply_markup,
        delete_user_msg=True,
    )
    return ConversationHandler.END


async def select_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Connect to the selected account, verify session validity, and present actions."""
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    await query.answer()
    phone = query.data.replace("select_", "").strip()
    user = update.effective_user
    user_id = user.id if user else 0

    account_repo = _get_account_repo(context)
    session_manager = _get_session_manager(context)

    # Verify that the account belongs to the user
    if account_repo is not None and user_id:
        account = await account_repo.get_account(user_id, phone)
        if account is None:
            await query.edit_message_text(text=ACCOUNT_NOT_FOUND_TEXT)
            return ConversationHandler.END

    # Verify session authorization with Telethon
    try:
        is_auth = await session_manager.is_authorized(phone)
    except Exception as e:
        logger.warning("Error checking authorization for %s: %s", phone, e)
        is_auth = False

    if not is_auth:
        logger.info("Session for %s has expired or is invalid. Cleaning up.", phone)
        # Clean up stale session file and database entry
        await session_manager.remove_session_file(phone)
        if account_repo is not None and user_id:
            await account_repo.remove_account(user_id, phone)

        remaining_phones = []
        if account_repo is not None and user_id:
            try:
                accs = await account_repo.get_user_accounts(user_id)
                remaining_phones = [a.phone_number for a in accs]
            except Exception as e:
                logger.debug("Error fetching remaining accounts: %s", e)

        reply_markup = account_list_keyboard(remaining_phones)
        text = (
            f"⚠️ نشست کاربری اکانت {phone} منقضی شده بود.\n"
            f"🗑️ این اکانت با موفقیت از لیست حساب‌های شما حذف شد.\n\n"
            f"{SESSION_EXPIRED_TEXT}"
        )
        await query.edit_message_text(text=text, reply_markup=reply_markup)
        return ConversationHandler.END

    # Update last_used timestamp
    if account_repo is not None and user_id:
        await account_repo.update_last_used(user_id, phone)

    context.user_data["current_phone"] = phone
    reply_markup = account_actions_keyboard(phone)
    await query.edit_message_text(
        text=format_account_actions(phone),
        reply_markup=reply_markup,
    )
    return ACCOUNT_ACTIONS


async def logout_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Terminate Telethon MTProto session, remove session file, and unbind from database."""
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    await query.answer()
    phone = query.data.replace("logout_", "").strip()
    user = update.effective_user
    user_id = user.id if user else 0

    auth_service = _get_auth_service(context)
    account_repo = _get_account_repo(context)
    op_repo: Optional[OperationLogRepository] = context.bot_data.get("op_repo")

    try:
        await auth_service.log_out(phone)
        if account_repo is not None and user_id:
            await account_repo.remove_account(user_id, phone)
        if op_repo is not None and user_id:
            await op_repo.log_operation(
                action="logout",
                user_id=user_id,
                phone_number=phone,
                status="success",
            )

        reply_markup = back_to_accounts_keyboard()
        await query.edit_message_text(
            text=format_logout_success(phone),
            reply_markup=reply_markup,
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error("Error logging out account %s: %s", phone, e)
        error_notice = format_bilingual_error(
            title_fa="خروج از اکانت",
            title_en="Account logout",
            error=str(e),
        )
        await query.edit_message_text(
            text=error_notice,
            reply_markup=back_to_accounts_keyboard(),
        )
        return ConversationHandler.END
