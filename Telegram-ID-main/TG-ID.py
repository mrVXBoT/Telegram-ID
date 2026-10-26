import os
import sys

# Ensure working directory is the script directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import logging
import json
import asyncio
import vobject
import re
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.tl.functions.contacts import GetContactsRequest, DeleteContactsRequest
from telethon.tl.functions.messages import GetDialogsRequest, GetFullChatRequest, ExportChatInviteRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon import functions
from telethon.tl.types import InputPeerEmpty, Chat, Channel, InputPeerChat
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, ConversationHandler

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for conversation handler
PHONE, CODE, WAITING_FOR_CODE, ACCOUNT_ACTIONS = range(4)

# Store active sessions
active_sessions = {}
# Store pending auth operations
pending_auth = {}
# Store user data
user_data_file = 'user_data.json'

# Load user data from file
def load_user_data():
    if os.path.exists(user_data_file):
        with open(user_data_file, 'r') as f:
            return json.load(f)
    return {}

# Save user data to file
def save_user_data(data):
    with open(user_data_file, 'w') as f:
        json.dump(data, f)

# User data
user_data = load_user_data()

# Helper function to create account actions keyboard
def create_account_actions_keyboard(phone):
    """Create the standard account actions keyboard for a given phone number."""
    return [
        [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone}')],
        [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone}')],
        [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone}')],
        [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone}')],
        [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone}')],
        [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone}')],
        [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone}')],
        [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone}')],
        [InlineKeyboardButton("🗑️ Delete All Contacts", callback_data=f'delete_contacts_{phone}')],
        [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone}')],
        [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone}')],
        [InlineKeyboardButton("Logout", callback_data=f'logout_{phone}')],
        [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
    ]

# Telegram API credentials
API_ID = 16208243
API_HASH = "a72ed8b5f6475a644c61f54ff367c1f6"

# Function to validate phone number
def validate_phone_number(phone):
    # Remove any spaces or dashes
    phone = re.sub(r'[\s-]', '', phone)
    
    # Make sure it starts with a plus sign
    if not phone.startswith('+'):
        phone = '+' + phone
    
    # Check if it's a valid phone number format
    if not re.match(r'^\+\d{10,15}$', phone):
        return None
    
    return phone

# Function to create a VCF file from contacts
def create_vcf_from_contacts(contacts):
    vcf_content = ""
    
    for contact in contacts:
        vcard = vobject.vCard()
        
        # Set the full name to the ID
        vcard.add('fn').value = str(contact.id)
        
        # Set the name components
        vcard.add('n')
        vcard.n.value = vobject.vcard.Name(family=str(contact.id), given='')
        
        # Add telephone number if available
        if hasattr(contact, 'phone') and contact.phone:
            tel = vcard.add('tel')
            tel.value = contact.phone
            
        # Add the contact to the VCF content
        vcf_content += vcard.serialize()
    
    return vcf_content

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send a message when the command /start is issued."""
    try:
        user_id = str(update.effective_user.id)
        if user_id in pending_auth:
            try:
                client = pending_auth[user_id].get('client')
                if client and client.is_connected():
                    await client.disconnect()
            except Exception:
                pass
            del pending_auth[user_id]

        keyboard = [
            [InlineKeyboardButton("Add Account", callback_data='add_account')],
            [InlineKeyboardButton("List Accounts", callback_data='list_accounts')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        chat_id = update.effective_chat.id if update.effective_chat else update.effective_user.id
        await context.bot.send_message(
            chat_id=chat_id,
            text='Welcome to Telegram Account Manager Bot!\n\n'
                 'Use this bot to manage your Telegram accounts, extract contacts, and handle authentication codes.',
            reply_markup=reply_markup
        )
        logger.info(f"Start command received from user {user_id}")
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        if update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="An error occurred. Please try again."
            )
    return ConversationHandler.END

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button presses."""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'cancel_auth':
        return await cancel(update, context)
        
    elif query.data == 'add_account':
        keyboard = [[InlineKeyboardButton("🔙 Cancel / انصراف", callback_data='cancel_auth')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text="Please send your phone number in international format (e.g., +989123456789):",
            reply_markup=reply_markup
        )
        return PHONE
    
    elif query.data == 'list_accounts':
        user_id = str(update.effective_user.id)
        if user_id in user_data and user_data[user_id]['accounts']:
            accounts_text = "Your accounts:\n\n"
            keyboard = []
            
            for phone, account_data in user_data[user_id]['accounts'].items():
                accounts_text += f"📱 {phone}\n"
                keyboard.append([InlineKeyboardButton(f"Select {phone}", callback_data=f'select_{phone}')])
            
            keyboard.append([InlineKeyboardButton("Back to Main Menu", callback_data='back_to_menu')])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text=accounts_text, reply_markup=reply_markup)
        else:
            keyboard = [[InlineKeyboardButton("Add Account", callback_data='add_account')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text="You don't have any accounts yet. Add an account first.",
                reply_markup=reply_markup
            )
        return ConversationHandler.END
    
    elif query.data == 'back_to_menu':
        keyboard = [
            [InlineKeyboardButton("Add Account", callback_data='add_account')],
            [InlineKeyboardButton("List Accounts", callback_data='list_accounts')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text='Welcome to Telegram Account Manager Bot!\n\n'
                 'Use this bot to manage your Telegram accounts, extract contacts, and handle authentication codes.',
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    
    elif query.data.startswith('select_'):
        phone = query.data.replace('select_', '')
        user_id = str(update.effective_user.id)
        
        # Check if the account exists
        if user_id in user_data and phone in user_data[user_id]['accounts']:
            # Create client and connect
            try:
                # Create session for this account if not already active
                if phone not in active_sessions:
                    client = TelegramClient(f"sessions/{phone}", API_ID, API_HASH)
                    await client.connect()
                    
                    if not await client.is_user_authorized():
                        await query.edit_message_text(text=f"Session for {phone} has expired. Please add the account again.")
                        if os.path.exists(f"sessions/{phone}.session"):
                            os.remove(f"sessions/{phone}.session")
                        
                        # Remove account from user data
                        del user_data[user_id]['accounts'][phone]
                        save_user_data(user_data)
                        
                        keyboard = [[InlineKeyboardButton("Add Account", callback_data='add_account')]]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await query.edit_message_text(
                            text="Session expired. Please add the account again.",
                            reply_markup=reply_markup
                        )
                        return ConversationHandler.END
                    
                    active_sessions[phone] = client
                
                # Show account actions with separate buttons for each ID length
                keyboard = create_account_actions_keyboard(phone)
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    text=f"Account: {phone}\nWhat would you like to do?",
                    reply_markup=reply_markup
                )
                context.user_data['current_phone'] = phone
                return ACCOUNT_ACTIONS
            
            except Exception as e:
                logger.error(f"Error selecting account: {e}")
                await query.edit_message_text(text=f"Error accessing account: {str(e)}")
                return ConversationHandler.END
        else:
            await query.edit_message_text(text="Account not found. Please add the account first.")
            return ConversationHandler.END
    
    elif query.data.startswith('check_contacts_'):
        phone = query.data.replace('check_contacts_', '')
        
        if phone in active_sessions:
            client = active_sessions[phone]
            
            try:
                # Get all contacts
                contacts = await client(GetContactsRequest(hash=0))
                
                # Send contact info
                await query.edit_message_text(
                    text=f"Account: {phone}\nFetching contacts information..."
                )
                
                # Send contact count information
                total_contacts = len(contacts.users)
                mutual_contacts = sum(1 for c in contacts.contacts if getattr(c, 'mutual', False))
                contact_info = f"Total contacts: {total_contacts}\nMutual contacts: {mutual_contacts}\n\n"
                
                # Count contacts with different ID lengths
                id_lengths = {7: 0, 8: 0, 9: 0, 10: 0, 11: 0}
                for contact in contacts.users:
                    user_id_str = str(contact.id)
                    if user_id_str.isdigit() and len(user_id_str) in id_lengths:
                        id_lengths[len(user_id_str)] += 1
                
                # Add counts to contact info
                for length, count in id_lengths.items():
                    contact_info += f"Contacts with {length} digit IDs: {count}\n"
                
                # Show some sample contacts if available
                contact_info += "\nSample contacts:\n"
                for contact in contacts.users[:5]:
                    contact_info += f"ID: {contact.id}"
                    if hasattr(contact, 'first_name') and contact.first_name:
                        contact_info += f", Name: {contact.first_name}"
                        if hasattr(contact, 'last_name') and contact.last_name:
                            contact_info += f" {contact.last_name}"
                    contact_info += "\n"
                
                # Return to account actions with updated keyboard
                keyboard = create_account_actions_keyboard(phone)
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text=contact_info,
                    reply_markup=reply_markup
                )
                
                return ACCOUNT_ACTIONS
            
            except Exception as e:
                logger.error(f"Error checking contacts: {e}")
                await query.edit_message_text(text=f"Error checking contacts: {str(e)}")
                return ConversationHandler.END
        else:
            await query.edit_message_text(text="Session not active. Please select the account again.")
            return ConversationHandler.END
    
    elif query.data.startswith('extract_'):
        # Parse the ID length and phone from the callback data
        parts = query.data.split('_')
        if len(parts) >= 3:
            id_length = parts[1]
            phone = '_'.join(parts[2:])  # Join remaining parts in case phone contains underscores
            
            if phone in active_sessions:
                client = active_sessions[phone]
                
                try:
                    # Get all contacts
                    contacts = await client(GetContactsRequest(hash=0))
                    
                    # Filter contacts with specific ID length
                    numeric_id_contacts = []
                    
                    if id_length == "7to9":
                        # Extract contacts with IDs ranging from 7 to 9 digits
                        for contact in contacts.users:
                            user_id_str = str(contact.id)
                            if user_id_str.isdigit() and 7 <= len(user_id_str) <= 9:
                                numeric_id_contacts.append(contact)
                        
                        # Send a new message to avoid "message not modified" error
                        await context.bot.send_message(
                            chat_id=update.effective_user.id,
                            text=f"Found {len(numeric_id_contacts)} contacts with 7-9 digit IDs. Preparing VCF file..."
                        )
                    else:
                        # Original code for specific ID length
                        id_length = int(id_length)
                        for contact in contacts.users:
                            user_id_str = str(contact.id)
                            if user_id_str.isdigit() and len(user_id_str) == id_length:
                                numeric_id_contacts.append(contact)
                        
                        # Send a new message to avoid "message not modified" error
                        await context.bot.send_message(
                            chat_id=update.effective_user.id,
                            text=f"Found {len(numeric_id_contacts)} contacts with {id_length} digit IDs. Preparing VCF file..."
                        )
                    
                    if numeric_id_contacts:
                        # Create VCF file
                        vcf_content = create_vcf_from_contacts(numeric_id_contacts)
                        
                        # Save to file
                        vcf_filename = f"{phone}_{id_length}digit_contacts.vcf"
                        with open(vcf_filename, 'w', encoding='utf-8') as f:
                            f.write(vcf_content)
                        
                        # Send file
                        with open(vcf_filename, 'rb') as f:
                            await context.bot.send_document(
                                chat_id=update.effective_user.id,
                                document=f,
                                filename=vcf_filename,
                                caption=f"Found {len(numeric_id_contacts)} contacts with {id_length} digit IDs"
                            )
                        
                        # Clean up
                        os.remove(vcf_filename)
                    else:
                        await context.bot.send_message(
                            chat_id=update.effective_user.id,
                            text=f"No contacts with {id_length} digit IDs found."
                        )
                    
                    # Return to account actions
                    keyboard = create_account_actions_keyboard(phone)
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        chat_id=update.effective_user.id,
                        text=f"Account: {phone}\nWhat would you like to do next?",
                        reply_markup=reply_markup
                    )
                    
                    return ACCOUNT_ACTIONS
                
                except Exception as e:
                    logger.error(f"Error extracting contacts: {e}")
                    await context.bot.send_message(
                        chat_id=update.effective_user.id,
                        text=f"Error extracting contacts: {str(e)}"
                    )
                    
                    # Return to account actions
                    keyboard = create_account_actions_keyboard(phone)
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        chat_id=update.effective_user.id,
                        text=f"Account: {phone}\nWhat would you like to do next?",
                        reply_markup=reply_markup
                    )
                    
                    return ACCOUNT_ACTIONS
            else:
                await query.edit_message_text(text="Session not active. Please select the account again.")
                return ConversationHandler.END
    
    elif query.data.startswith('get_code_'):
        phone = query.data.replace('get_code_', '')
        
        if phone in active_sessions:
            client = active_sessions[phone]
            
            try:
                # Get the last 20 messages from Telegram's official account (777000)
                messages = await client.get_messages(777000, limit=20)
                
                # Find the most recent code message
                code_message = None
                for message in messages:
                    if message and message.text:
                        # Look for 5-digit code pattern in any language
                        code_match = re.search(r'\b\d{5}\b', message.text)
                        if code_match:
                            code_message = message.text
                            break
                
                if code_message:
                    # Return to account actions with updated keyboard
                    keyboard = create_account_actions_keyboard(phone)
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        text=f"Latest code from Telegram for {phone}:\n\n{code_message}",
                        reply_markup=reply_markup
                    )
                else:
                    # Return to account actions with updated keyboard
                    keyboard = create_account_actions_keyboard(phone)
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        text=f"No recent code messages found for {phone}. Please try again later.",
                        reply_markup=reply_markup
                    )
                
                return ACCOUNT_ACTIONS
            
            except Exception as e:
                logger.error(f"Error getting code: {e}")
                # Return to account actions with updated keyboard
                keyboard = create_account_actions_keyboard(phone)
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text=f"Error getting code: {str(e)}\nPlease try again.",
                    reply_markup=reply_markup
                )
                return ACCOUNT_ACTIONS
        else:
            await query.edit_message_text(text="Session not active. Please select the account again.")
            return ConversationHandler.END
    
    elif query.data.startswith('logout_'):
        phone = query.data.replace('logout_', '')
        user_id = str(update.effective_user.id)
        
        if phone in active_sessions:
            client = active_sessions[phone]
            
            try:
                # Disconnect and log out
                await client.log_out()
                
                # Remove session file
                if os.path.exists(f"sessions/{phone}.session"):
                    os.remove(f"sessions/{phone}.session")
                
                # Remove from active sessions
                del active_sessions[phone]
                
                # Remove from user data
                if user_id in user_data and phone in user_data[user_id]['accounts']:
                    del user_data[user_id]['accounts'][phone]
                    save_user_data(user_data)
                
                keyboard = [[InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    text=f"Successfully logged out from {phone}",
                    reply_markup=reply_markup
                )
                return ConversationHandler.END
            
            except Exception as e:
                logger.error(f"Error logging out: {e}")
                await query.edit_message_text(text=f"Error logging out: {str(e)}")
                return ConversationHandler.END
        else:
            await query.edit_message_text(text="Session not active. Please select the account again.")
            return ConversationHandler.END
    
    elif query.data.startswith('list_chats_'):
        phone = query.data.replace('list_chats_', '')
        if phone in active_sessions:
            client = active_sessions[phone]
            try:
                # Fetch dialogs
                dialogs = await client(GetDialogsRequest(
                    offset_date=None,
                    offset_id=0,
                    offset_peer=InputPeerEmpty(),
                    limit=100,
                    hash=0
                ))
                chats = dialogs.chats
                
                # Filter chats created by the user
                all_creator_chats = [chat for chat in chats if getattr(chat, 'creator', False)]
                
                # Debug log all creator chats
                logger.info(f"=== ALL CREATOR CHATS DEBUG ===")
                for i, chat in enumerate(all_creator_chats):
                    logger.info(f"Chat {i+1}: '{getattr(chat, 'title', 'No Title')}' | Type: {type(chat).__name__} | Creator: {getattr(chat, 'creator', False)} | Megagroup: {getattr(chat, 'megagroup', 'N/A')}")
                
                # Remove migrated chats to avoid duplicates
                # Find all supergroups and their migrated_from_chat_id
                migrated_chat_ids = set()
                for chat in all_creator_chats:
                    if isinstance(chat, Channel) and getattr(chat, 'megagroup', False):
                        try:
                            # Get full info to find migrated_from_chat_id
                            full = await client(GetFullChannelRequest(channel=chat))
                            if hasattr(full.full_chat, 'migrated_from_chat_id'):
                                migrated_from_id = full.full_chat.migrated_from_chat_id
                                if migrated_from_id:
                                    migrated_chat_ids.add(migrated_from_id)
                                    logger.info(f"Supergroup {chat.title} migrated from chat ID: {migrated_from_id}")
                        except:
                            pass
                
                # Filter out migrated chats
                creator_chats = []
                for chat in all_creator_chats:
                    if isinstance(chat, Chat) and chat.id in migrated_chat_ids:
                        logger.info(f"SKIPPING migrated chat: {getattr(chat, 'title', 'No Title')} (ID: {chat.id})")
                        continue
                    creator_chats.append(chat)
                
                logger.info(f"Final creator chats after removing migrated: {len(creator_chats)}")
                
                # Separate channels and groups
                channels = []
                groups = []
                regular_chats = []
                
                for chat in creator_chats:
                    if isinstance(chat, Channel):
                        # Follow HV.py logic: megagroup=True means it's a supergroup
                        if getattr(chat, 'megagroup', False):
                            groups.append(chat)
                            logger.info(f"Added to GROUPS: {getattr(chat, 'title', 'No Title')}")
                        else:
                            channels.append(chat)
                            logger.info(f"Added to CHANNELS: {getattr(chat, 'title', 'No Title')}")
                    elif isinstance(chat, Chat):
                        # This shouldn't happen after filtering, but keep as fallback
                        logger.info(f"Found regular Chat: {getattr(chat, 'title', 'No Title')} - investigating if it's actually a group")
                        regular_chats.append(chat)
                        logger.info(f"Added to REGULAR CHATS: {getattr(chat, 'title', 'No Title')}")
                
                # Build formatted message
                chat_info = f"📱 Account: {phone}\n\n"
                
                # Show Channels first
                if channels:
                    chat_info += "📺 「 کانال‌های شما / Your Channels 」\n\n"
                    for i, channel in enumerate(channels, 1):
                        # Build link
                        username = getattr(channel, 'username', None)
                        if username:
                            link = f"https://t.me/{username}"
                        else:
                            try:
                                invite = await client(ExportChatInviteRequest(peer=channel))
                                link = invite.link
                            except Exception:
                                raw_id = str(channel.id)
                                if raw_id.startswith('-100'):
                                    link_id = raw_id[4:]
                                else:
                                    link_id = raw_id
                                link = f"https://t.me/c/{link_id}"
                        
                        # Get creation date
                        try:
                            msgs = await client.get_messages(channel, limit=1, reverse=True)
                            creation_date = msgs[0].date.strftime('%Y-%m-%d') if msgs else 'نامشخص'
                            year = msgs[0].date.year if msgs else 'نامشخص'
                        except Exception:
                            creation_date = 'نامشخص'
                            year = 'نامشخص'
                        
                        # Get history visibility for channels - Simple version
                        hidden_str = '👁️ Visible / قابل مشاهده'
                        try:
                            full = await client(GetFullChannelRequest(channel=channel))
                            
                            # Check hidden_prehistory (main indicator)
                            if hasattr(full.full_chat, 'hidden_prehistory'):
                                hidden = full.full_chat.hidden_prehistory
                                hidden_str = '🔒 Hidden / مخفی' if hidden else '👁️ Visible / قابل مشاهده'
                                logger.info(f"Channel {channel.title} hidden_prehistory: {hidden}")
                            
                            # Check available_min_id as backup
                            elif hasattr(full.full_chat, 'available_min_id'):
                                min_id = full.full_chat.available_min_id
                                if min_id is not None and min_id > 1:
                                    hidden_str = '🔒 Hidden / مخفی'
                                else:
                                    hidden_str = '👁️ Visible / قابل مشاهده'
                                    
                        except Exception as e:
                            logger.error(f"Error getting channel history for {channel.title}: {e}")
                            hidden_str = '❓ Unknown / نامشخص'
                        
                        chat_info += f"{i}. 『 {channel.title} 』\n"
                        chat_info += f"   🔗 Link: {link}\n"
                        chat_info += f"   📅 تاریخ ساخت: {creation_date} (سال {year})\n"
                        chat_info += f"   👁️ تاریخچه: {hidden_str}\n\n"
                
                # Show Groups/Supergroups
                if groups:
                    chat_info += "👥 「 گروه‌های شما / Your Groups 」\n\n"
                    for i, group in enumerate(groups, 1):
                        # Build link
                        username = getattr(group, 'username', None)
                        if username:
                            link = f"https://t.me/{username}"
                        else:
                            try:
                                invite = await client(ExportChatInviteRequest(peer=group))
                                link = invite.link
                            except Exception:
                                raw_id = str(group.id)
                                if raw_id.startswith('-100'):
                                    link_id = raw_id[4:]
                                else:
                                    link_id = raw_id
                                link = f"https://t.me/c/{link_id}"
                        
                        # Get creation date
                        try:
                            msgs = await client.get_messages(group, limit=1, reverse=True)
                            creation_date = msgs[0].date.strftime('%Y-%m-%d') if msgs else 'نامشخص'
                            year = msgs[0].date.year if msgs else 'نامشخص'
                        except Exception:
                            creation_date = 'نامشخص'
                            year = 'نامشخص'
                        
                        # Get history visibility for groups - Simple version with detailed logging
                        hidden_str = '👁️ Visible / قابل مشاهده'
                        try:
                            full = await client(GetFullChannelRequest(channel=group))
                            
                            # Detailed logging for debugging
                            logger.info(f"=== ANALYZING GROUP: {group.title} ===")
                            logger.info(f"Group ID: {group.id}")
                            logger.info(f"Group username: {getattr(group, 'username', 'None')}")
                            logger.info(f"Group megagroup: {getattr(group, 'megagroup', 'None')}")
                            logger.info(f"Group creator: {getattr(group, 'creator', 'None')}")
                            
                            # Check all relevant attributes
                            attrs = ['hidden_prehistory', 'available_min_id', 'migrated_from_chat_id', 'participants_hidden']
                            for attr in attrs:
                                value = getattr(full.full_chat, attr, 'NOT_FOUND')
                                logger.info(f"  {attr}: {value}")
                            
                            # Check hidden_prehistory (main indicator)
                            if hasattr(full.full_chat, 'hidden_prehistory'):
                                hidden = full.full_chat.hidden_prehistory
                                hidden_str = '🔒 Hidden / مخفی' if hidden else '👁️ Visible / قابل مشاهده'
                                logger.info(f"RESULT for {group.title}: hidden_prehistory={hidden} -> {hidden_str}")
                            
                            # Check available_min_id as backup
                            elif hasattr(full.full_chat, 'available_min_id'):
                                min_id = full.full_chat.available_min_id
                                if min_id is not None and min_id > 1:
                                    hidden_str = '🔒 Hidden / مخفی'
                                    logger.info(f"RESULT for {group.title}: available_min_id={min_id} > 1 -> Hidden")
                                else:
                                    hidden_str = '👁️ Visible / قابل مشاهده'
                                    logger.info(f"RESULT for {group.title}: available_min_id={min_id} <= 1 -> Visible")
                            else:
                                logger.warning(f"NO ATTRIBUTE FOUND for {group.title} - defaulting to Visible")
                                    
                        except Exception as e:
                            logger.error(f"Error getting group history for {group.title}: {e}")
                            hidden_str = '❓ Unknown / نامشخص'
                        
                        chat_info += f"{i}. 『 {group.title} 』\n"
                        chat_info += f"   🔗 Link: {link}\n"
                        chat_info += f"   📅 تاریخ ساخت: {creation_date} (سال {year})\n"
                        chat_info += f"   👁️ تاریخچه: {hidden_str}\n\n"
                
                # Show regular chats if any
                if regular_chats:
                    chat_info += "💬 「 چت‌های معمولی / Regular Chats 」\n\n"
                    for i, chat in enumerate(regular_chats, 1):
                        # Get creation date
                        try:
                            msgs = await client.get_messages(chat, limit=1, reverse=True)
                            creation_date = msgs[0].date.strftime('%Y-%m-%d') if msgs else 'نامشخص'
                            year = msgs[0].date.year if msgs else 'نامشخص'
                        except Exception:
                            creation_date = 'نامشخص'
                            year = 'نامشخص'
                        
                        # Advanced check for regular chats - try to detect hidden history by message access
                        hidden_str = '👁️ Visible / قابل مشاهده'
                        try:
                            # Detailed logging for debugging
                            logger.info(f"=== ANALYZING REGULAR CHAT: {chat.title} ===")
                            logger.info(f"Chat ID: {chat.id}")
                            logger.info(f"Chat creator: {getattr(chat, 'creator', 'None')}")
                            
                            # Get full chat info
                            full = await client(GetFullChatRequest(chat_id=chat.id))
                            
                            # Check if this chat has been migrated to a supergroup
                            migrated_to = getattr(full.full_chat, 'migrated_to', None)
                            logger.info(f"  migrated_to: {migrated_to if migrated_to else 'NOT_FOUND'}")
                            
                            if migrated_to:
                                # This is a migrated chat, check the supergroup version
                                try:
                                    supergroup_full = await client(GetFullChannelRequest(channel=migrated_to))
                                    if hasattr(supergroup_full.full_chat, 'hidden_prehistory'):
                                        hidden = supergroup_full.full_chat.hidden_prehistory
                                        hidden_str = '🔒 Hidden / مخفی' if hidden else '👁️ Visible / قابل مشاهده'
                                        logger.info(f"RESULT for migrated {chat.title}: hidden_prehistory={hidden} -> {hidden_str}")
                                    else:
                                        logger.info(f"Migrated supergroup found but no hidden_prehistory attribute")
                                except Exception as e:
                                    logger.error(f"Error checking migrated supergroup for {chat.title}: {e}")
                            else:
                                # Try alternative method: check message access patterns
                                try:
                                    # Try to get messages from the beginning
                                    first_messages = await client.get_messages(chat, limit=5, reverse=True)
                                    recent_messages = await client.get_messages(chat, limit=5)
                                    
                                    if first_messages and recent_messages:
                                        first_id = first_messages[0].id if first_messages else 0
                                        recent_id = recent_messages[0].id if recent_messages else 0
                                        
                                        logger.info(f"Message analysis for {chat.title}:")
                                        logger.info(f"  First accessible message ID: {first_id}")
                                        logger.info(f"  Recent message ID: {recent_id}")
                                        
                                        # If first message ID is significantly higher than 1, might indicate hidden history
                                        if first_id > 10:  # threshold for detecting gaps
                                            logger.info(f"Gap detected: first_id={first_id} > 10, might be hidden")
                                            # Additional check: try to access message ID 1
                                            try:
                                                first_msg = await client.get_messages(chat, ids=[1])
                                                if not first_msg or not first_msg[0]:
                                                    hidden_str = '🔒 Hidden / مخفی'
                                                    logger.info(f"RESULT for {chat.title}: Cannot access message 1 -> Hidden")
                                                else:
                                                    logger.info(f"Can access message 1 -> Visible")
                                            except:
                                                hidden_str = '🔒 Hidden / مخفی'
                                                logger.info(f"RESULT for {chat.title}: Error accessing message 1 -> Hidden")
                                        else:
                                            logger.info(f"No significant gap detected -> Visible")
                                    else:
                                        logger.info(f"No messages found or accessible")
                                        
                                except Exception as e:
                                    logger.error(f"Error analyzing messages for {chat.title}: {e}")
                            
                            # Check other attributes
                            attrs = ['participants_count', 'admins_count']
                            for attr in attrs:
                                value = getattr(full.full_chat, attr, 'NOT_FOUND')
                                logger.info(f"  {attr}: {value}")
                                
                        except Exception as e:
                            logger.error(f"Error getting regular chat history for {chat.title}: {e}")
                            logger.info(f"FALLBACK for {chat.title}: Setting to Visible (default for regular chats)")
                        
                        chat_info += f"{i}. 『 {chat.title} 』\n"
                        chat_info += f"   📅 تاریخ ساخت: {creation_date} (سال {year})\n"
                        chat_info += f"   👁️ تاریخچه: {hidden_str}\n\n"
                
                if not creator_chats:
                    chat_info += "❌ هیچ کانال، گروه یا چتی که مالک آن باشید پیدا نشد.\n"
                    chat_info += "❌ No channels, groups or chats found that you own."
                
                keyboard = [
                    [InlineKeyboardButton("🔙 بازگشت به عملیات اکانت", callback_data=f'select_{phone}')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    text=chat_info,
                    reply_markup=reply_markup
                )
                return ACCOUNT_ACTIONS
            except Exception as e:
                logger.error(f"Error listing chats: {e}")
                await query.edit_message_text(text=f"Error listing chats: {str(e)}")
                return ConversationHandler.END
        else:
            await query.edit_message_text(text="Session not active. Please select the account again.")
            return ConversationHandler.END
    
    elif query.data.startswith('export_mutual_'):
        phone = query.data.replace('export_mutual_', '')
        if phone in active_sessions:
            client = active_sessions[phone]
            try:
                contacts = await client(GetContactsRequest(hash=0))
                mutual_ids = [c.user_id for c in contacts.contacts if getattr(c, 'mutual', False)]
                mutual_users = [u for u in contacts.users if u.id in mutual_ids]
                if mutual_users:
                    vcf_content = create_vcf_from_contacts(mutual_users)
                    vcf_filename = f"{phone}_mutual_contacts.vcf"
                    with open(vcf_filename, 'w', encoding='utf-8') as f:
                        f.write(vcf_content)
                    with open(vcf_filename, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=update.effective_user.id,
                            document=f,
                            filename=vcf_filename,
                            caption=f"Exported {len(mutual_users)} mutual contacts"
                        )
                    os.remove(vcf_filename)
                else:
                    await context.bot.send_message(chat_id=update.effective_user.id, text="No mutual contacts found.")
                    # Return to account actions
                    keyboard = create_account_actions_keyboard(phone)
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(text=f"Account: {phone}\nSelect next action:", reply_markup=reply_markup)
                    return ACCOUNT_ACTIONS
            except Exception as e:
                logger.error(f"Error exporting mutual contacts: {e}")
                await query.edit_message_text(text=f"Error exporting mutual contacts: {str(e)}")
                return ConversationHandler.END
        else:
            await query.edit_message_text(text="Session not active. Please select the account again.")
            return ConversationHandler.END
    
    elif query.data.startswith('delete_contacts_'):
        phone = query.data.replace('delete_contacts_', '')
        if phone in active_sessions:
            client = active_sessions[phone]
            try:
                # Get all contacts first
                contacts = await client(GetContactsRequest(hash=0))
                
                if not contacts.users:
                    await query.edit_message_text(
                        text=f"📱 Account: {phone}\n\n❌ هیچ مخاطبی برای حذف پیدا نشد.\n❌ No contacts found to delete.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 بازگشت به عملیات اکانت", callback_data=f'select_{phone}')]
                        ])
                    )
                    return ACCOUNT_ACTIONS
                
                total_contacts = len(contacts.users)
                
                # Show confirmation message first
                await query.edit_message_text(
                    text=f"📱 Account: {phone}\n\n"
                         f"⚠️ هشدار! شما در حال حذف کردن {total_contacts} مخاطب هستید.\n"
                         f"⚠️ Warning! You are about to delete {total_contacts} contacts.\n\n"
                         f"آیا مطمئن هستید؟ / Are you sure?",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ بله، همه را حذف کن / Yes, Delete All", callback_data=f'confirm_delete_{phone}')],
                        [InlineKeyboardButton("❌ انصراف / Cancel", callback_data=f'select_{phone}')]
                    ])
                )
                return ACCOUNT_ACTIONS
                
            except Exception as e:
                logger.error(f"Error preparing to delete contacts: {e}")
                await query.edit_message_text(
                    text=f"❌ خطا در آماده‌سازی حذف مخاطبین: {str(e)}\n❌ Error preparing to delete contacts: {str(e)}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت به عملیات اکانت", callback_data=f'select_{phone}')]
                    ])
                )
                return ACCOUNT_ACTIONS
        else:
            await query.edit_message_text(text="Session not active. Please select the account again.")
            return ConversationHandler.END
    
    elif query.data.startswith('confirm_delete_'):
        phone = query.data.replace('confirm_delete_', '')
        if phone in active_sessions:
            client = active_sessions[phone]
            try:
                # Get all contacts
                contacts = await client(GetContactsRequest(hash=0))
                
                if not contacts.users:
                    await query.edit_message_text(
                        text=f"📱 Account: {phone}\n\n❌ هیچ مخاطبی برای حذف پیدا نشد.\n❌ No contacts found to delete.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 بازگشت به عملیات اکانت", callback_data=f'select_{phone}')]
                        ])
                    )
                    return ACCOUNT_ACTIONS
                
                total_contacts = len(contacts.users)
                
                # Update message to show deletion progress
                await query.edit_message_text(
                    text=f"📱 Account: {phone}\n\n"
                         f"🔄 در حال حذف {total_contacts} مخاطب...\n"
                         f"🔄 Deleting {total_contacts} contacts...\n\n"
                         f"لطفاً منتظر بمانید... / Please wait..."
                )
                
                # Prepare user IDs for deletion
                user_ids = [user.id for user in contacts.users]
                deleted_count = 0
                failed_count = 0
                
                # Delete contacts in batches of 100 (Telegram API limit)
                batch_size = 100
                for i in range(0, len(user_ids), batch_size):
                    batch = user_ids[i:i+batch_size]
                    try:
                        # Use DeleteContactsRequest to delete contacts
                        await client(DeleteContactsRequest(id=batch))
                        deleted_count += len(batch)
                        
                        # Update progress
                        progress = (i + len(batch)) * 100 // len(user_ids)
                        await query.edit_message_text(
                            text=f"📱 Account: {phone}\n\n"
                                 f"🔄 پیشرفت: {progress}% ({deleted_count}/{total_contacts})\n"
                                 f"🔄 Progress: {progress}% ({deleted_count}/{total_contacts})\n\n"
                                 f"در حال حذف مخاطبین... / Deleting contacts..."
                        )
                        
                        # Small delay between batches to avoid rate limiting
                        await asyncio.sleep(1)
                        
                    except Exception as batch_error:
                        logger.error(f"Error deleting batch: {batch_error}")
                        failed_count += len(batch)
                
                # Final result
                success_count = deleted_count
                result_text = (
                    f"📱 Account: {phone}\n\n"
                    f"✅ عملیات حذف مخاطبین تکمیل شد!\n"
                    f"✅ Contact deletion completed!\n\n"
                    f"📊 نتیجه / Result:\n"
                    f"🗑️ حذف شده: {success_count}\n"
                    f"❌ ناموفق: {failed_count}\n"
                    f"📊 کل: {total_contacts}\n\n"
                    f"🗑️ Deleted: {success_count}\n"
                    f"❌ Failed: {failed_count}\n"
                    f"📊 Total: {total_contacts}"
                )
                
                keyboard = [
                    [InlineKeyboardButton("🔙 بازگشت به عملیات اکانت", callback_data=f'select_{phone}')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text=result_text,
                    reply_markup=reply_markup
                )
                
                return ACCOUNT_ACTIONS
                
            except Exception as e:
                logger.error(f"Error deleting contacts: {e}")
                await query.edit_message_text(
                    text=f"❌ خطا در حذف مخاطبین: {str(e)}\n❌ Error deleting contacts: {str(e)}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت به عملیات اکانت", callback_data=f'select_{phone}')]
                    ])
                )
                return ACCOUNT_ACTIONS
        else:
            await query.edit_message_text(text="Session not active. Please select the account again.")
            return ConversationHandler.END
    
    return ConversationHandler.END

async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle phone number input."""
    phone_number = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    # Validate phone number
    phone_number = validate_phone_number(phone_number)
    if not phone_number:
        await update.message.reply_text(
            "Invalid phone number format. Please send your phone number in international format (e.g., +989123456789)"
        )
        return PHONE
    
    # Store phone number in context
    context.user_data['phone'] = phone_number
    
    # Create directory for sessions if it doesn't exist
    os.makedirs('sessions', exist_ok=True)
    
    try:
        # Create client
        client = TelegramClient(f"sessions/{phone_number}", API_ID, API_HASH)
        await client.connect()
        
        if await client.is_user_authorized():
            # Already authorized
            active_sessions[phone_number] = client
            
            # Update user data
            if user_id not in user_data:
                user_data[user_id] = {'accounts': {}}
            
            if 'accounts' not in user_data[user_id]:
                user_data[user_id]['accounts'] = {}
            
            user_data[user_id]['accounts'][phone_number] = {'added_at': str(update.message.date)}
            save_user_data(user_data)
            
            keyboard = create_account_actions_keyboard(phone_number)
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                text=f"Account {phone_number} is already authorized!",
                reply_markup=reply_markup
            )
            return ConversationHandler.END
        
        # Send code request
        sent_code = await client.send_code_request(phone_number)
        pending_auth[user_id] = {
            'phone': phone_number,
            'client': client,
            'phone_code_hash': getattr(sent_code, 'phone_code_hash', None)
        }
        
        keyboard = [[InlineKeyboardButton("❌ Cancel / انصراف", callback_data='cancel_auth')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Verification code sent to {phone_number}!\nPlease enter the code you received (or send /cancel to abort):",
            reply_markup=reply_markup
        )
        return CODE
    
    except Exception as e:
        logger.error(f"Error in phone handler: {e}")
        await update.message.reply_text(f"Error: {str(e)}\nPlease try again with a valid phone number.")
        return ConversationHandler.END

async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle verification code input."""
    raw_code = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    if user_id not in pending_auth:
        await update.message.reply_text("Session expired. Please send /start to begin again.")
        return ConversationHandler.END
    
    code = re.sub(r'[\s-]', '', raw_code)
    phone_number = pending_auth[user_id]['phone']
    client = pending_auth[user_id]['client']
    phone_code_hash = pending_auth[user_id].get('phone_code_hash')
    
    try:
        if phone_code_hash:
            await client.sign_in(phone_number, code, phone_code_hash=phone_code_hash)
        else:
            await client.sign_in(phone_number, code)
        
        # Store the active session
        active_sessions[phone_number] = client
        
        # Update user data
        if user_id not in user_data:
            user_data[user_id] = {'accounts': {}}
        
        if 'accounts' not in user_data[user_id]:
            user_data[user_id]['accounts'] = {}
        
        user_data[user_id]['accounts'][phone_number] = {'added_at': str(update.message.date)}
        save_user_data(user_data)
        
        # Clean up pending auth
        del pending_auth[user_id]
        
        # Show account actions with separate buttons for each ID length
        keyboard = create_account_actions_keyboard(phone_number)
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Successfully logged in to account {phone_number}!",
            reply_markup=reply_markup
        )
        return ACCOUNT_ACTIONS
    
    except SessionPasswordNeededError:
        await update.message.reply_text(
            "This account has two-factor authentication enabled. "
            "Please enter your password:"
        )
        context.user_data['awaiting_2fa'] = True
        return WAITING_FOR_CODE
    
    except PhoneCodeInvalidError:
        await update.message.reply_text(
            "Invalid code. Please try again:"
        )
        return CODE
    
    except Exception as e:
        logger.error(f"Error in code handler: {e}")
        await update.message.reply_text(f"Error: {str(e)}")
        
        # Clean up
        if client and client.is_connected():
            await client.disconnect()
        
        if user_id in pending_auth:
            del pending_auth[user_id]
        
        return ConversationHandler.END

async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 2FA password input."""
    password = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    if user_id not in pending_auth:
        await update.message.reply_text("Session expired. Please start over.")
        return ConversationHandler.END
    
    phone_number = pending_auth[user_id]['phone']
    client = pending_auth[user_id]['client']
    
    try:
        await client.sign_in(password=password)
        
        # Store the active session
        active_sessions[phone_number] = client
        
        # Update user data
        if user_id not in user_data:
            user_data[user_id] = {'accounts': {}}
        
        if 'accounts' not in user_data[user_id]:
            user_data[user_id]['accounts'] = {}
        
        user_data[user_id]['accounts'][phone_number] = {'added_at': str(update.message.date)}
        save_user_data(user_data)
        
        # Clean up pending auth
        del pending_auth[user_id]
        
        # Show account actions with separate buttons for each ID length
        keyboard = create_account_actions_keyboard(phone_number)
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Successfully logged in to account {phone_number}!",
            reply_markup=reply_markup
        )
        return ACCOUNT_ACTIONS
    
    except Exception as e:
        logger.error(f"Error in password handler: {e}")
        await update.message.reply_text(f"Error: {str(e)}")
        
        # Clean up
        if client and client.is_connected():
            await client.disconnect()
        
        if user_id in pending_auth:
            del pending_auth[user_id]
        
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel and end the conversation."""
    user_id = str(update.effective_user.id)
    if user_id in pending_auth:
        try:
            client = pending_auth[user_id].get('client')
            if client and client.is_connected():
                await client.disconnect()
        except Exception:
            pass
        del pending_auth[user_id]
        
    keyboard = [
        [InlineKeyboardButton("Add Account", callback_data='add_account')],
        [InlineKeyboardButton("List Accounts", callback_data='list_accounts')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            'Operation cancelled. Choose an option:',
            reply_markup=reply_markup
        )
    elif update.message:
        await update.message.reply_text(
            'Operation cancelled. Choose an option:',
            reply_markup=reply_markup
        )
    return ConversationHandler.END

async def default_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any unhandled messages."""
    if update.message:
        keyboard = [
            [InlineKeyboardButton("Add Account", callback_data='add_account')],
            [InlineKeyboardButton("List Accounts", callback_data='list_accounts')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            'Please send /start to open the menu or select an option below:',
            reply_markup=reply_markup
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}")
    try:
        if update and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="An error occurred. Please try again or contact support."
            )
    except Exception as e:
        logger.error(f"Error in error handler: {e}")

def main() -> None:
    """Start the bot."""
    # Create the Application
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8619968352:AAEFW0ui0QkXX9SKzPztPSzzzN7nourBxo4")
    application = Application.builder().token(BOT_TOKEN).build()

    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_handler)
        ],
        states={
            PHONE: [
                CommandHandler("start", start),
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)
            ],
            CODE: [
                CommandHandler("start", start),
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, code_handler)
            ],
            WAITING_FOR_CODE: [
                CommandHandler("start", start),
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler)
            ],
            ACCOUNT_ACTIONS: [
                CommandHandler("start", start),
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(button_handler)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
            CallbackQueryHandler(button_handler)
        ],
        allow_reentry=True,
        per_message=False
    )
    
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, default_message_handler))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the Bot
    logger.critical("Starting bot...")
    print("\033[1;32mDEV : VX | BoT STARTED $ join @l27_0\033[0m")
    application.run_polling()

if __name__ == '__main__':
    main() 
