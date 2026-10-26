"""
bot.messages
============
Bilingual (English and Persian) message templates, user prompts, and formatting helpers
for the Telegram Account Manager bot.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

# --- Menu & Auth Text Templates ---

WELCOME_TEXT = (
    "🤖 ربات حرفه‌ای مدیریت اکانت و استخراج مخاطبین تلگرام\n"
    "Welcome to Telegram Account Manager Bot!\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "👋 به سامانه مدیریت هوشمند اکانت‌های تلگرام خوش آمدید.\n\n"
    "✨ امکانات کلیدی ربات:\n"
    "▫️ 📱 مدیریت همزمان چندین اکانت تلگرام بدون تداخل\n"
    "▫️ 🎯 استخراج مخاطبین بر اساس تعداد ارقام (۷ تا ۱۱ رقمی)\n"
    "▫️ 📦 استخراج یکجای مخاطبین ۷ تا ۹ رقمی در قالب یک فایل\n"
    "▫️ 📥 صدور فایل مخاطبین (VCF) سازگار با گوشی و گوگل کانتکتس\n"
    "▫️ 👥 فیلتر و استخراج مخاطبین دوطرفه (Mutual Contacts)\n"
    "▫️ 💬 مشاهده لیست چت‌ها، کانال‌ها و گروه‌های تحت مالکیت\n"
    "▫️ 🔑 دریافت آخرین کدهای تایید ورود ارسالی تلگرام\n\n"
    "Use this bot to manage your Telegram accounts, extract contacts, "
    "and handle authentication codes.\n\n"
    "👇 لطفاً برای شروع، یکی از گزینه‌های زیر را انتخاب فرمایید:"
)

HELP_GUIDE_TEXT = (
    "📖 راهنمای جامع امکانات ربات مدیریت اکانت تلگرام\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "🎯 استخراج مخاطبین بر اساس ارقام (Digit ID Extraction):\n"
    "▫️ آیدی‌های ۷ و ۸ رقمی: کاربران قدیمی تلگرام (سال‌های ۲۰۱۴ تا ۲۰۱۶).\n"
    "▫️ آیدی‌های ۹ رقمی: کاربران چند سال گذشته (۲۰۱۶ تا ۲۰۱۹).\n"
    "▫️ آیدی‌های ۱۰ و ۱۱ رقمی: کاربران جدید تلگرام (۲۰۲۰ تا کنون).\n"
    "▫️ خروجی یکجای ۷ تا ۹ رقمی: روشی سریع برای دریافت یک فایل جامع از تمامی اکانت‌های قدیمی.\n\n"
    "📥 فایل خروجی VCF:\n"
    "▫️ فایل‌های استخراجی با فرمت استاندارد vCard 3.0 تولید می‌شوند.\n"
    "▫️ می‌توانید این فایل‌ها را مستقیماً در تلفن همراه (اندروید یا آیفون) یا Google Contacts با یک کلیک ایمپورت کنید.\n\n"
    "👥 مخاطبین دوطرفه (Mutual Contacts):\n"
    "▫️ افرادی را استخراج می‌کند که هر دو طرف شماره یکدیگر را در مخاطبین ذخیره دارند.\n\n"
    "💬 مدیریت چت‌ها و گروه‌ها (Creator Chats):\n"
    "▫️ کانال‌ها و گروه‌های تحت مالکیت اکانت را همراه با لینک دعوت، تاریخ ساخت و وضعیت تاریخچه فهرست می‌کند.\n\n"
    "🔑 دریافت آخرین کد ورود (Telegram Login Code):\n"
    "▫️ پیام‌های امنیتی سرویس تلگرام (۷۷۷۰۰۰) را بررسی کرده و کد تأیید ورود را برای شما آماده می‌کند.\n\n"
    "🗑️ حذف مخاطبین:\n"
    "▫️ مخاطبین ذخیره‌شده روی سرور تلگرام را به صورت دسته‌ای و با درصد زنده حذف می‌نماید."
)

ADD_ACCOUNT_PROMPT = (
    "📱 افزودن اکانت جدید تلگرام | Add Telegram Account\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "لطفاً شماره موبایل خود را همراه با کد کشور (فرمت بین‌المللی E.164) ارسال فرمایید:\n\n"
    "💡 مثال:\n"
    "▫️ `+989123456789`\n"
    "▫️ `+12345678901`\n\n"
    "Please send your phone number in international format (e.g., +989123456789):"
)

VERIFICATION_CODE_PROMPT = (
    "🔐 مرحله دریافت کد ورود | Verification Code\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "کد ورود تلگرام به شماره `{phone}` ارسال شد.\n\n"
    "📩 لطفاً کد دریافت شده را ارسال نمایید (نیازی به فاصله نیست).\n"
    "اگر اکانت شما دارای رمز دومرحله‌ای (2FA) است، در مرحله بعد درخواست خواهد شد.\n\n"
    "Verification code sent to {phone}!\n"
    "Please enter the code you received (or send /cancel to abort):"
)

INVALID_PHONE_TEXT = (
    "❌ فرمت شماره ارسال‌شده نامعتبر است.\n"
    "لطفاً شماره را به همراه کد کشور ارسال فرمایید (مثال: `+989123456789`)\n\n"
    "Invalid phone number format. Please send your phone number in "
    "international format (e.g., +989123456789)"
)

ALREADY_AUTHORIZED_TEXT = (
    "✅ این اکانت قبلاً با موفقیت متصل شده است:\n"
    "Account {phone} is already authorized!"
)

LOGIN_SUCCESS_TEXT = (
    "🎉 ورود به اکانت با موفقیت انجام شد:\n"
    "Successfully logged in to account {phone}!"
)

TWO_FA_PROMPT = (
    "🔒 رمز تأیید دومرحله‌ای | Two-Step Verification\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "این اکانت دارای رمز دومرحله‌ای (Cloud Password) است.\n"
    "لطفاً کلمه عبور اکانت خود را وارد نمایید:\n\n"
    "This account has two-factor authentication enabled. "
    "Please enter your password:"
)

INVALID_CODE_TEXT = (
    "❌ کد وارد شده نامعتبر است. لطفاً مجدداً تلاش کنید:\n"
    "Invalid code. Please try again:"
)

INVALID_PASSWORD_TEXT = (
    "❌ رمز دومرحله‌ای وارد شده نادرست است. لطفاً دوباره وارد کنید:\n"
    "Invalid 2FA password. Please try again."
)

OPERATION_CANCELLED_TEXT = (
    "❌ عملیات لغو شد. یکی از گزینه‌های زیر را انتخاب کنید:\n"
    "Operation cancelled. Choose an option:"
)

DEFAULT_FALLBACK_TEXT = (
    "👋 برای مشاهده منو و دستورات، گزینه زیر را انتخاب کنید یا دستور /start را بفرستید:\n"
    "Please send /start to open the menu or select an option below:"
)

ERROR_GENERIC_TEXT = (
    "❌ خطایی رخ داد. لطفاً مجدداً تلاش کنید.\n"
    "An error occurred. Please try again."
)

ERROR_SUPPORT_TEXT = (
    "❌ خطایی رخ داد. لطفاً دوباره تلاش نمایید یا با پشتیبانی تماس بگیرید.\n"
    "An error occurred. Please try again or contact support."
)

ACCOUNT_NOT_FOUND_TEXT = (
    "❌ اکانت مورد نظر یافت نشد. لطفاً ابتدا اکانت را اضافه کنید.\n"
    "Account not found. Please add the account first."
)

SESSION_NOT_ACTIVE_TEXT = (
    "⚠️ سشن اکانت فعال نیست. لطفاً مجدداً اکانت را انتخاب فرمایید.\n"
    "Session not active. Please select the account again."
)

SESSION_EXPIRED_TEXT = (
    "⚠️ نشست کاربری منقضی شده است. لطفاً اکانت را مجدداً اضافه نمایید.\n"
    "Session expired. Please add the account again."
)

SESSION_EXPIRED_RESTART_TEXT = (
    "⚠️ نشست کاربری منقضی شد. لطفاً با ارسال /start از نو شروع کنید.\n"
    "Session expired. Please send /start to begin again."
)

NO_ACCOUNTS_TEXT = (
    "ℹ️ شما در حال حاضر هیچ اکانت متصلی ندارید. لطفاً ابتدا یک اکانت اضافه فرمایید.\n\n"
    "You don't have any accounts yet. Add an account first."
)

ACCOUNTS_LIST_HEADER = (
    "📱 لیست اکانت‌های متصل شما | Your Linked Accounts\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "اکانت مورد نظر خود را جهت انجام عملیات انتخاب نمایید:\n\n"
    "Your accounts:\n\n"
)

LOGOUT_SUCCESS_TEXT = (
    "🚪 با موفقیت از اکانت خارج شدید:\n"
    "Successfully logged out from {phone}"
)

ACCOUNT_ACTIONS_PROMPT = (
    "⚙️ پنل مدیریت اکانت: `{phone}`\n"
    "وضعیت: 🟢 متصل و آماده به کار\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "📌 جهت استخراج مخاطبین یا استفاده از سایر ابزارها، گزینه مورد نظر را انتخاب نمایید:\n\n"
    "Account: {phone}\nWhat would you like to do?"
)

ACCOUNT_ACTIONS_NEXT_PROMPT = (
    "⚙️ پنل مدیریت اکانت: `{phone}`\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "📌 عملیات بعدی را انتخاب فرمایید:\n\n"
    "Account: {phone}\nWhat would you like to do next?"
)

# --- Contact Operations Text Templates ---

FETCHING_CONTACTS_TEXT = "📱 اکانت | Account: {phone}\n⏳ در حال دریافت اطلاعات مخاطبین... | Fetching contacts information..."

EXTRACTING_CONTACTS_TEXT = (
    "🔍 {count} مخاطب {id_length} رقمی یافت شد. در حال ساخت فایل...\n"
    "Found {count} contacts with {id_length} digit IDs. Preparing VCF file..."
)

NO_CONTACTS_FOUND_TEXT = (
    "❌ هیچ مخاطبی با آیدی {id_length} رقمی یافت نشد.\n"
    "No contacts with {id_length} digit IDs found."
)

VCF_CAPTION_TEXT = "📁 استخراج {count} مخاطب ({id_length} رقمی) | Found {count} contacts with {id_length} digit IDs"

NO_MUTUAL_CONTACTS_TEXT = (
    "👥 مخاطبین دوطرفه | Mutual Contacts\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "❌ هیچ مخاطب دوطرفه‌ای در این اکانت یافت نشد.\n"
    "No mutual contacts found."
)

MUTUAL_VCF_CAPTION_TEXT = "📁 استخراج {count} مخاطب دوطرفه | Exported {count} mutual contacts"

DELETE_WARNING_TEXT = (
    "📱 Account: {phone}\n\n"
    "⚠️ هشدار! شما در حال حذف کردن {total_contacts} مخاطب هستید.\n"
    "⚠️ Warning! You are about to delete {total_contacts} contacts.\n\n"
    "آیا مطمئن هستید؟ / Are you sure?"
)

NO_CONTACTS_TO_DELETE_TEXT = (
    "📱 Account: {phone}\n\n"
    "❌ هیچ مخاطبی برای حذف پیدا نشد.\n"
    "❌ No contacts found to delete."
)

DELETE_PROGRESS_START_TEXT = (
    "📱 Account: {phone}\n\n"
    "🔄 در حال حذف {total_contacts} مخاطب...\n"
    "🔄 Deleting {total_contacts} contacts...\n\n"
    "لطفاً منتظر بمانید... / Please wait..."
)

DELETE_PROGRESS_TEXT = (
    "📱 Account: {phone}\n\n"
    "🔄 پیشرفت: {progress}% ({deleted_count}/{total_contacts})\n"
    "🔄 Progress: {progress}% ({deleted_count}/{total_contacts})\n\n"
    "در حال حذف مخاطبین... / Deleting contacts..."
)

DELETE_RESULT_TEXT = (
    "📱 Account: {phone}\n\n"
    "✅ عملیات حذف مخاطبین تکمیل شد!\n"
    "✅ Contact deletion completed!\n\n"
    "📊 نتیجه / Result:\n"
    "🗑️ حذف شده: {success_count}\n"
    "❌ ناموفق: {failed_count}\n"
    "📊 کل: {total_contacts}\n\n"
    "🗑️ Deleted: {success_count}\n"
    "❌ Failed: {failed_count}\n"
    "📊 Total: {total_contacts}"
)

DELETE_ERROR_TEXT = (
    "❌ خطا در حذف مخاطبین: {error}\n"
    "❌ Error deleting contacts: {error}"
)

DELETE_PREPARE_ERROR_TEXT = (
    "❌ خطا در آماده‌سازی حذف مخاطبین: {error}\n"
    "❌ Error preparing to delete contacts: {error}"
)

# --- Chat & Auth Code Text Templates ---

LATEST_CODE_TEXT = (
    "🔑 آخرین پیام سرویس تلگرام | Telegram Service Code\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "📱 اکانت | Account: {phone}\n\n"
    "Latest code from Telegram for {phone}:\n\n{code_message}"
)

NO_CODE_FOUND_TEXT = (
    "ℹ️ هیچ پیام ورود جدیدی از سرویس تلگرام یافت نشد.\n"
    "No recent code messages found for {phone}. Please try again later."
)

CODE_ERROR_TEXT = (
    "❌ خطا در دریافت کد: {error}\n"
    "Error getting code: {error}\n"
    "لطفاً دوباره تلاش فرمایید | Please try again."
)

BACK_TO_ACTIONS_TEXT = "🔙 بازگشت"
CANCEL_PERSIAN_ENGLISH = "❌ انصراف"
CANCEL_RED_PERSIAN_ENGLISH = "❌ انصراف"
YES_DELETE_ALL = "🗑️ بله، همه حذف شوند"
CANCEL_DELETE = "❌ انصراف"


# --- Formatting Helpers ---


def format_welcome() -> str:
    """Return main welcome message."""
    return WELCOME_TEXT


def format_verification_prompt(phone: str) -> str:
    """Format SMS verification code prompt with phone number."""
    return VERIFICATION_CODE_PROMPT.format(phone=phone)


def format_already_authorized(phone: str) -> str:
    """Format already authorized notice."""
    return ALREADY_AUTHORIZED_TEXT.format(phone=phone)


def format_login_success(phone: str) -> str:
    """Format login success message."""
    return LOGIN_SUCCESS_TEXT.format(phone=phone)


def format_account_actions(phone: str, next_action: bool = False) -> str:
    """Format account actions menu header prompt."""
    if next_action:
        return ACCOUNT_ACTIONS_NEXT_PROMPT.format(phone=phone)
    return ACCOUNT_ACTIONS_PROMPT.format(phone=phone)


def format_accounts_list(accounts: Iterable[str]) -> str:
    """Format list of phone accounts for account list menu."""
    acc_list = list(accounts)
    if not acc_list:
        return NO_ACCOUNTS_TEXT
    res = ACCOUNTS_LIST_HEADER
    for phone in acc_list:
        res += f"📱 {phone}\n"
    return res


def format_logout_success(phone: str) -> str:
    """Format logout success message."""
    return LOGOUT_SUCCESS_TEXT.format(phone=phone)


def format_delete_warning(phone: str, total_contacts: int) -> str:
    """Format bilingual delete warning message."""
    return DELETE_WARNING_TEXT.format(phone=phone, total_contacts=total_contacts)


def format_no_contacts_to_delete(phone: str) -> str:
    """Format notice when there are no contacts to delete."""
    return NO_CONTACTS_TO_DELETE_TEXT.format(phone=phone)


def format_delete_progress_start(phone: str, total_contacts: int) -> str:
    """Format initial progress message before batches run."""
    return DELETE_PROGRESS_START_TEXT.format(
        phone=phone, total_contacts=total_contacts
    )


def format_delete_progress(
    phone: str, progress: int, deleted_count: int, total_contacts: int
) -> str:
    """Format live percentage progress during batch deletion."""
    return DELETE_PROGRESS_TEXT.format(
        phone=phone,
        progress=progress,
        deleted_count=deleted_count,
        total_contacts=total_contacts,
    )


def format_delete_result(
    phone: str, success_count: int, failed_count: int, total_contacts: int
) -> str:
    """Format final batch deletion summary report."""
    return DELETE_RESULT_TEXT.format(
        phone=phone,
        success_count=success_count,
        failed_count=failed_count,
        total_contacts=total_contacts,
    )


def format_contacts_summary(phone: str, summary: Mapping[str, Any]) -> str:
    """
    Format contacts overview message with bilingual Persian & English headers:
    Total contacts, Mutual contacts, counts by digit length, top sample contacts.
    """
    total = summary.get("total", 0)
    mutual = summary.get("mutual", 0)
    breakdown: Mapping[int, int] = summary.get("breakdown", {})
    samples = summary.get("samples", [])

    info = (
        f"📊 آمار مخاطبین | Contacts Overview\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 اکانت | Account: {phone}\n"
        f"👥 کل مخاطبین | Total contacts: {total}\n"
        f"🤝 مخاطبین دوطرفه | Mutual contacts: {mutual}\n\n"
        f"🎯 تفکیک ارقام | Digit ID Breakdown:\n"
    )
    for length in [7, 8, 9, 10, 11]:
        count = breakdown.get(length, 0)
        info += f"▫️ {length} رقمی | Contacts with {length} digit IDs: {count}\n"

    info += "\n🔍 نمونه مخاطبین | Sample contacts:\n"
    for contact in samples:
        cid = getattr(contact, "id", None)
        if cid is None and isinstance(contact, dict):
            cid = contact.get("id")
        fname = getattr(contact, "first_name", None)
        if fname is None and isinstance(contact, dict):
            fname = contact.get("first_name")
        lname = getattr(contact, "last_name", None)
        if lname is None and isinstance(contact, dict):
            lname = contact.get("last_name")

        line = f"ID: {cid}"
        if fname:
            line += f", Name: {fname}"
            if lname:
                line += f" {lname}"
        info += f"{line}\n"

    return info


def format_bilingual_error(title_fa: str, title_en: str, error: str) -> str:
    """Format a standard bilingual error notice for inline displays."""
    return (
        f"❌ خطا در {title_fa} | Error: {title_en}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 جزئیات خطا | Details: {error}\n\n"
        f"💡 لطفاً مجدداً تلاش نمایید | Please try again."
    )


def format_creator_chats(phone: str, chats: Iterable[Any]) -> str:
    """
    Format user-owned channels, supergroups, and basic chats with
    links, creation dates/years, and history visibility.
    """
    chat_list = list(chats)
    header = f"📱 Account: {phone}\n\n"

    channels = [c for c in chat_list if getattr(c, "type", "") == "channel" or getattr(c, "is_channel", False)]
    groups = [
        c
        for c in chat_list
        if getattr(c, "type", "") in {"supergroup", "group"}
        or getattr(c, "is_supergroup", False)
        or getattr(c, "is_group", False)
    ]
    regular = [
        c
        for c in chat_list
        if getattr(c, "type", "") not in {"channel", "supergroup", "group"}
        and not getattr(c, "is_channel", False)
        and not getattr(c, "is_supergroup", False)
        and not getattr(c, "is_group", False)
    ]

    out = header
    if channels:
        out += "📺 「 کانال‌های شما / Your Channels 」\n\n"
        for i, ch in enumerate(channels, 1):
            title = getattr(ch, "title", "Untitled")
            link = getattr(ch, "link", "N/A")
            cdate = getattr(ch, "creation_date", "نامشخص") or "نامشخص"
            cyear = getattr(ch, "creation_year", "نامشخص") or "نامشخص"
            hvis = getattr(ch, "history_visibility", None)
            if hvis == "Hidden" or getattr(ch, "hidden_prehistory", False) is True:
                h_str = "🔒 Hidden / مخفی"
            elif hvis == "Visible" or getattr(ch, "hidden_prehistory", False) is False:
                h_str = "👁️ Visible / قابل مشاهده"
            else:
                h_str = "❓ Unknown / نامشخص"

            out += f"{i}. 『 {title} 』\n"
            out += f"   🔗 Link: {link}\n"
            out += f"   📅 تاریخ ساخت: {cdate} (سال {cyear})\n"
            out += f"   👁️ تاریخچه: {h_str}\n\n"

    if groups:
        out += "👥 「 گروه‌های شما / Your Groups 」\n\n"
        for i, grp in enumerate(groups, 1):
            title = getattr(grp, "title", "Untitled")
            link = getattr(grp, "link", "N/A")
            cdate = getattr(grp, "creation_date", "نامشخص") or "نامشخص"
            cyear = getattr(grp, "creation_year", "نامشخص") or "نامشخص"
            hvis = getattr(grp, "history_visibility", None)
            if hvis == "Hidden" or getattr(grp, "hidden_prehistory", False) is True:
                h_str = "🔒 Hidden / مخفی"
            elif hvis == "Visible" or getattr(grp, "hidden_prehistory", False) is False:
                h_str = "👁️ Visible / قابل مشاهده"
            else:
                h_str = "👁️ Visible / قابل مشاهده"

            out += f"{i}. 『 {title} 』\n"
            out += f"   🔗 Link: {link}\n"
            out += f"   📅 تاریخ ساخت: {cdate} (سال {cyear})\n"
            out += f"   👁️ تاریخچه: {h_str}\n\n"

    if regular:
        out += "💬 「 چت‌های معمولی / Regular Chats 」\n\n"
        for i, chat in enumerate(regular, 1):
            title = getattr(chat, "title", "Untitled")
            cdate = getattr(chat, "creation_date", "نامشخص") or "نامشخص"
            cyear = getattr(chat, "creation_year", "نامشخص") or "نامشخص"
            h_str = "👁️ Visible / قابل مشاهده"
            out += f"{i}. 『 {title} 』\n"
            out += f"   📅 تاریخ ساخت: {cdate} (سال {cyear})\n"
            out += f"   👁️ تاریخچه: {h_str}\n\n"

    if not channels and not groups and not regular:
        out += "No creator chats found."

    return out


def format_latest_code(phone: str, code_message: str) -> str:
    """Format retrieved login code message."""
    return LATEST_CODE_TEXT.format(phone=phone, code_message=code_message)


def format_no_code_found(phone: str) -> str:
    """Format notice when no recent code was found."""
    return NO_CODE_FOUND_TEXT.format(phone=phone)
