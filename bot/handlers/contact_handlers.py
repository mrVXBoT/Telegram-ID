"""
bot.handlers.contact_handlers
=============================
Handlers for contact inspection, digit length extraction (7-11, 7to9),
mutual contacts export via streaming VCF, and batch deletion.
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards import (
    account_actions_keyboard,
    back_to_actions_keyboard,
    delete_confirm_keyboard,
)
from bot.messages import (
    DELETE_ERROR_TEXT,
    DELETE_PREPARE_ERROR_TEXT,
    EXTRACTING_CONTACTS_TEXT,
    FETCHING_CONTACTS_TEXT,
    MUTUAL_VCF_CAPTION_TEXT,
    NO_CONTACTS_FOUND_TEXT,
    NO_MUTUAL_CONTACTS_TEXT,
    VCF_CAPTION_TEXT,
    format_account_actions,
    format_bilingual_error,
    format_contacts_summary,
    format_delete_progress,
    format_delete_progress_start,
    format_delete_result,
    format_delete_warning,
    format_no_contacts_to_delete,
)
from bot.states import ACCOUNT_ACTIONS
from services.contact_service import ContactService
from services.session_manager import TelethonSessionManager
from utils.vcf import (
    format_mutual_vcf_filename,
    format_vcf_filename,
    generate_vcf_stream,
)

logger = logging.getLogger(__name__)


def _get_contact_service(context: ContextTypes.DEFAULT_TYPE) -> ContactService:
    cs = context.bot_data.get("contact_service")
    if cs is None:
        sm = context.bot_data.get("session_manager")
        if sm is None:
            sm = TelethonSessionManager()
            context.bot_data["session_manager"] = sm
        cs = ContactService(sm)
        context.bot_data["contact_service"] = cs
    return cs


async def check_contacts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fetch all contacts, compute length breakdown, and display summary report."""
    query = update.callback_query
    if not query or not query.data:
        return ACCOUNT_ACTIONS

    await query.answer()
    phone = query.data.replace("check_contacts_", "").strip()

    try:
        await query.edit_message_text(text=FETCHING_CONTACTS_TEXT.format(phone=phone))
        contact_service = _get_contact_service(context)
        summary = await contact_service.get_contacts_summary(phone)

        text = format_contacts_summary(phone, summary)
        reply_markup = account_actions_keyboard(phone)
        await query.edit_message_text(text=text, reply_markup=reply_markup)
        return ACCOUNT_ACTIONS

    except Exception as e:
        logger.error("Error checking contacts for %s: %s", phone, e)
        reply_markup = account_actions_keyboard(phone)
        error_notice = format_bilingual_error("بررسی آمار مخاطبین", "Checking contacts", str(e))
        await query.edit_message_text(
            text=f"{error_notice}\nError checking contacts: {str(e)}",
            reply_markup=reply_markup,
        )
        return ACCOUNT_ACTIONS


async def extract_contacts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Extract contacts by digit length (7, 8, 9, 10, 11, or 7to9),
    stream VCF directly via send_document without disk I/O, and re-render menu.
    """
    query = update.callback_query
    if not query or not query.data:
        return ACCOUNT_ACTIONS

    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 3:
        return ACCOUNT_ACTIONS

    id_length = parts[1]
    phone = "_".join(parts[2:]).strip()

    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else (user.id if user else 0)

    try:
        contact_service = _get_contact_service(context)
        contacts = await contact_service.extract_contacts_by_length(phone, id_length)

        # Send intermediate progress message
        await context.bot.send_message(
            chat_id=chat_id,
            text=EXTRACTING_CONTACTS_TEXT.format(count=len(contacts), id_length=id_length),
        )

        if contacts:
            filename = format_vcf_filename(phone, id_length)
            stream = generate_vcf_stream(contacts, filename=filename)
            caption = VCF_CAPTION_TEXT.format(count=len(contacts), id_length=id_length)

            await context.bot.send_document(
                chat_id=chat_id,
                document=stream,
                filename=filename,
                caption=caption,
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=NO_CONTACTS_FOUND_TEXT.format(id_length=id_length),
            )

        # Present account actions menu for next action
        reply_markup = account_actions_keyboard(phone)
        await context.bot.send_message(
            chat_id=chat_id,
            text=format_account_actions(phone, next_action=True),
            reply_markup=reply_markup,
        )
        return ACCOUNT_ACTIONS

    except Exception as e:
        logger.error("Error extracting contacts for %s: %s", phone, e)
        error_notice = format_bilingual_error("استخراج مخاطبین", "Extracting contacts", str(e))
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{error_notice}\nError extracting contacts: {str(e)}",
        )
        reply_markup = account_actions_keyboard(phone)
        await context.bot.send_message(
            chat_id=chat_id,
            text=format_account_actions(phone, next_action=True),
            reply_markup=reply_markup,
        )
        return ACCOUNT_ACTIONS


async def export_mutual_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Export mutual contacts to an in-memory VCF and send document."""
    query = update.callback_query
    if not query or not query.data:
        return ACCOUNT_ACTIONS

    await query.answer()
    phone = query.data.replace("export_mutual_", "").strip()

    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else (user.id if user else 0)

    try:
        contact_service = _get_contact_service(context)
        mutual_contacts = await contact_service.get_mutual_contacts(phone)

        if mutual_contacts:
            filename = format_mutual_vcf_filename(phone)
            stream = generate_vcf_stream(mutual_contacts, filename=filename)
            caption = MUTUAL_VCF_CAPTION_TEXT.format(count=len(mutual_contacts))

            await context.bot.send_document(
                chat_id=chat_id,
                document=stream,
                filename=filename,
                caption=caption,
            )

            reply_markup = account_actions_keyboard(phone)
            await context.bot.send_message(
                chat_id=chat_id,
                text=format_account_actions(phone, next_action=True),
                reply_markup=reply_markup,
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=NO_MUTUAL_CONTACTS_TEXT,
            )
            reply_markup = account_actions_keyboard(phone)
            await query.edit_message_text(
                text=format_account_actions(phone, next_action=True),
                reply_markup=reply_markup,
            )

        return ACCOUNT_ACTIONS

    except Exception as e:
        logger.error("Error exporting mutual contacts for %s: %s", phone, e)
        reply_markup = account_actions_keyboard(phone)
        error_notice = format_bilingual_error("استخراج مخاطبین دوطرفه", "Exporting mutual contacts", str(e))
        await query.edit_message_text(
            text=f"{error_notice}\nError exporting mutual contacts: {str(e)}",
            reply_markup=reply_markup,
        )
        return ACCOUNT_ACTIONS


async def delete_contacts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fetch contacts count and present bilingual deletion confirmation warning."""
    query = update.callback_query
    if not query or not query.data:
        return ACCOUNT_ACTIONS

    await query.answer()
    phone = query.data.replace("delete_contacts_", "").strip()

    try:
        contact_service = _get_contact_service(context)
        all_contacts = await contact_service.get_all_contacts(phone)

        if not all_contacts:
            reply_markup = back_to_actions_keyboard(phone)
            await query.edit_message_text(
                text=format_no_contacts_to_delete(phone),
                reply_markup=reply_markup,
            )
            return ACCOUNT_ACTIONS

        total = len(all_contacts)
        reply_markup = delete_confirm_keyboard(phone)
        await query.edit_message_text(
            text=format_delete_warning(phone, total),
            reply_markup=reply_markup,
        )
        return ACCOUNT_ACTIONS

    except Exception as e:
        logger.error("Error preparing contact deletion for %s: %s", phone, e)
        reply_markup = back_to_actions_keyboard(phone)
        await query.edit_message_text(
            text=DELETE_PREPARE_ERROR_TEXT.format(error=str(e)),
            reply_markup=reply_markup,
        )
        return ACCOUNT_ACTIONS


async def confirm_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Perform batch deletion of contacts in chunks of 100 with live UI progress edits."""
    query = update.callback_query
    if not query or not query.data:
        return ACCOUNT_ACTIONS

    await query.answer()
    phone = query.data.replace("confirm_delete_", "").strip()

    try:
        contact_service = _get_contact_service(context)
        all_contacts = await contact_service.get_all_contacts(phone)

        if not all_contacts:
            reply_markup = back_to_actions_keyboard(phone)
            await query.edit_message_text(
                text=format_no_contacts_to_delete(phone),
                reply_markup=reply_markup,
            )
            return ACCOUNT_ACTIONS

        total = len(all_contacts)
        await query.edit_message_text(text=format_delete_progress_start(phone, total))

        async def progress_cb(deleted: int, total_cnt: int) -> None:
            pct = (deleted * 100) // total_cnt if total_cnt else 100
            try:
                await query.edit_message_text(
                    text=format_delete_progress(phone, pct, deleted, total_cnt)
                )
            except Exception:
                pass

        result = await contact_service.delete_all_contacts(
            phone=phone,
            progress_callback=progress_cb,
            batch_delay=1.0,
        )

        reply_markup = back_to_actions_keyboard(phone)
        await query.edit_message_text(
            text=format_delete_result(phone, result.deleted, result.failed, result.total),
            reply_markup=reply_markup,
        )
        return ACCOUNT_ACTIONS

    except Exception as e:
        logger.error("Error deleting contacts for %s: %s", phone, e)
        reply_markup = back_to_actions_keyboard(phone)
        await query.edit_message_text(
            text=DELETE_ERROR_TEXT.format(error=str(e)),
            reply_markup=reply_markup,
        )
        return ACCOUNT_ACTIONS
