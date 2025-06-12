import os
import logging
import json
import asyncio
import vobject
import re
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.tl.functions.messages import GetDialogsRequest, GetFullChatRequest, ExportChatInviteRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import InputPeerEmpty, Chat, Channel, InputPeerChat
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, ConversationHandler

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.CRITICAL
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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    try:
        keyboard = [
            [InlineKeyboardButton("Add Account", callback_data='add_account')],
            [InlineKeyboardButton("List Accounts", callback_data='list_accounts')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send a new message instead of editing
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text='Welcome to Telegram Account Manager Bot!\n\n'
                 'Use this bot to manage your Telegram accounts, extract contacts, and handle authentication codes.',
            reply_markup=reply_markup
        )
        logger.info(f"Start command received from user {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="An error occurred. Please try again."
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button presses."""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'add_account':
        await query.edit_message_text(text="Please send your phone number in international format (e.g., +989123456789)")
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
                keyboard = [
                    [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone}')],
                    [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone}')],
                    [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone}')],
                    [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone}')],
                    [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone}')],
                    [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone}')],
                    [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone}')],
                    [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone}')],
                    [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone}')],
                    [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone}')],
                    [InlineKeyboardButton("Logout", callback_data=f'logout_{phone}')],
                    [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
                ]
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
                keyboard = [
                    [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone}')],
                    [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone}')],
                    [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone}')],
                    [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone}')],
                    [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone}')],
                    [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone}')],
                    [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone}')],
                    [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone}')],
                    [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone}')],
                    [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone}')],
                    [InlineKeyboardButton("Logout", callback_data=f'logout_{phone}')],
                    [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
                ]
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
                    keyboard = [
                        [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone}')],
                        [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone}')],
                        [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone}')],
                        [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone}')],
                        [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone}')],
                        [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone}')],
                        [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone}')],
                        [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone}')],
                        [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone}')],
                        [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone}')],
                        [InlineKeyboardButton("Logout", callback_data=f'logout_{phone}')],
                        [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
                    ]
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
                    keyboard = [
                        [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone}')],
                        [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone}')],
                        [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone}')],
                        [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone}')],
                        [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone}')],
                        [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone}')],
                        [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone}')],
                        [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone}')],
                        [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone}')],
                        [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone}')],
                        [InlineKeyboardButton("Logout", callback_data=f'logout_{phone}')],
                        [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
                    ]
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
                    keyboard = [
                        [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone}')],
                        [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone}')],
                        [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone}')],
                        [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone}')],
                        [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone}')],
                        [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone}')],
                        [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone}')],
                        [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone}')],
                        [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone}')],
                        [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone}')],
                        [InlineKeyboardButton("Logout", callback_data=f'logout_{phone}')],
                        [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        text=f"Latest code from Telegram for {phone}:\n\n{code_message}",
                        reply_markup=reply_markup
                    )
                else:
                    # Return to account actions with updated keyboard
                    keyboard = [
                        [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone}')],
                        [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone}')],
                        [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone}')],
                        [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone}')],
                        [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone}')],
                        [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone}')],
                        [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone}')],
                        [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone}')],
                        [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone}')],
                        [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone}')],
                        [InlineKeyboardButton("Logout", callback_data=f'logout_{phone}')],
                        [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        text=f"No recent code messages found for {phone}. Please try again later.",
                        reply_markup=reply_markup
                    )
                
                return ACCOUNT_ACTIONS
            
            except Exception as e:
                logger.error(f"Error getting code: {e}")
                # Return to account actions with updated keyboard
                keyboard = [
                    [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone}')],
                    [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone}')],
                    [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone}')],
                    [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone}')],
                    [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone}')],
                    [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone}')],
                    [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone}')],
                    [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone}')],
                    [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone}')],
                    [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone}')],
                    [InlineKeyboardButton("Logout", callback_data=f'logout_{phone}')],
                    [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
                ]
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
                # Filter chats created by the user, preferring channels (supergroups/channels)
                creator_chats = [chat for chat in chats if getattr(chat, 'creator', False)]
                channel_chats = [c for c in creator_chats if isinstance(c, Channel)]
                chat_chats = [c for c in creator_chats if isinstance(c, Chat)]
                my_chats = channel_chats if channel_chats else chat_chats
                chat_info = f"Account: {phone}\nYour created chats:\n"
                for chat in my_chats:
                    # Build invite or public link
                    username = getattr(chat, 'username', None)
                    if username:
                        link = f"https://t.me/{username}"
                    else:
                        try:
                            invite = await client(ExportChatInviteRequest(peer=chat))
                            link = invite.link
                        except Exception:
                            raw_id = str(chat.id)
                            if raw_id.startswith('-100'):
                                link_id = raw_id[4:]
                            elif raw_id.startswith('-'):
                                link_id = raw_id[1:]
                            else:
                                link_id = raw_id
                            link = f"https://t.me/c/{link_id}"
                    # Determine creation year via earliest message
                    try:
                        msgs = await client.get_messages(chat, limit=1, reverse=True)
                        year = msgs[0].date.year if msgs else 'Unknown'
                    except Exception:
                        year = 'Unknown'
                    # Determine hidden history if available
                    hidden = None
                    try:
                        if isinstance(chat, Channel):
                            full = await client(GetFullChannelRequest(channel=chat))
                            hidden = getattr(full.full_chat, 'hidden_prehistory', None)
                        else:
                            full = await client(GetFullChatRequest(chat_id=chat.id))
                            hidden = getattr(full.full_chat, 'hidden_prehistory', None)
                    except Exception:
                        hidden = None
                    # Map hidden flag to readable string
                    if hidden is None:
                        hidden_str = 'Unknown'
                    elif hidden:
                        hidden_str = 'Hidden'
                    else:
                        hidden_str = 'Visible'
                    chat_info += f"{link} - Created: {year}, History: {hidden_str}\n"
                keyboard = [
                    [InlineKeyboardButton("Back to Account Actions", callback_data=f'select_{phone}')]
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
                    keyboard = [
                        [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone}')],
                        [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone}')],
                        [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone}')],
                        [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone}')],
                        [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone}')],
                        [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone}')],
                        [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone}')],
                        [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone}')],
                        [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone}')],
                        [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone}')],
                        [InlineKeyboardButton("Logout", callback_data=f'logout_{phone}')],
                        [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
                    ]
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
            
            keyboard = [
                [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone_number}')],
                [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone_number}')],
                [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone_number}')],
                [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone_number}')],
                [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone_number}')],
                [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone_number}')],
                [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone_number}')],
                [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone_number}')],
                [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone_number}')],
                [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone_number}')],
                [InlineKeyboardButton("Logout", callback_data=f'logout_{phone_number}')],
                [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                text=f"Account {phone_number} is already authorized!",
                reply_markup=reply_markup
            )
            return ConversationHandler.END
        
        # Send code request
        await client.send_code_request(phone_number)
        pending_auth[user_id] = {'phone': phone_number, 'client': client}
        
        await update.message.reply_text(
            "Verification code sent! Please enter the code you received:"
        )
        return CODE
    
    except Exception as e:
        logger.error(f"Error in phone handler: {e}")
        await update.message.reply_text(f"Error: {str(e)}\nPlease try again with a valid phone number.")
        return ConversationHandler.END

async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle verification code input."""
    code = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    if user_id not in pending_auth:
        await update.message.reply_text("Session expired. Please start over.")
        return ConversationHandler.END
    
    phone_number = pending_auth[user_id]['phone']
    client = pending_auth[user_id]['client']
    
    try:
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
        keyboard = [
            [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone_number}')],
            [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone_number}')],
            [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone_number}')],
            [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone_number}')],
            [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone_number}')],
            [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone_number}')],
            [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone_number}')],
            [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone_number}')],
            [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone_number}')],
            [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone_number}')],
            [InlineKeyboardButton("Logout", callback_data=f'logout_{phone_number}')],
            [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
        ]
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
        keyboard = [
            [InlineKeyboardButton("Extract 7 Digit IDs", callback_data=f'extract_7_{phone_number}')],
            [InlineKeyboardButton("Extract 8 Digit IDs", callback_data=f'extract_8_{phone_number}')],
            [InlineKeyboardButton("Extract 9 Digit IDs", callback_data=f'extract_9_{phone_number}')],
            [InlineKeyboardButton("Extract 7-9 Digit IDs", callback_data=f'extract_7to9_{phone_number}')],
            [InlineKeyboardButton("Extract 10 Digit IDs", callback_data=f'extract_10_{phone_number}')],
            [InlineKeyboardButton("Extract 11 Digit IDs", callback_data=f'extract_11_{phone_number}')],
            [InlineKeyboardButton("Check All Contacts", callback_data=f'check_contacts_{phone_number}')],
            [InlineKeyboardButton("Export Mutual Contacts", callback_data=f'export_mutual_{phone_number}')],
            [InlineKeyboardButton("List Chats", callback_data=f'list_chats_{phone_number}')],
            [InlineKeyboardButton("Get Latest Code", callback_data=f'get_code_{phone_number}')],
            [InlineKeyboardButton("Logout", callback_data=f'logout_{phone_number}')],
            [InlineKeyboardButton("Back to Account List", callback_data='list_accounts')]
        ]
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
    await update.message.reply_text('Operation cancelled.')
    return ConversationHandler.END

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
    application = Application.builder().token("7464338818:AAHxs6U53SQX22H1CwgRRxXbSQM00O0X814").build()

    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_handler)
        ],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_handler)],
            WAITING_FOR_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler)],
            ACCOUNT_ACTIONS: [CallbackQueryHandler(button_handler)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False  # Changed to False to fix the warning
    )
    
    application.add_handler(conv_handler)
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the Bot
    logger.critical("Starting bot...")
    print("\033[1;32mDEV : VX | BoT STARTED $ join @l27_0\033[0m")
    application.run_polling()

if __name__ == '__main__':
    main() 