import pyotp
import asyncio
import time
import logging
import random
import string
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
from dotenv import load_dotenv
import os
import json

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "8343363851").split(","))) if os.getenv("ADMIN_IDS") else [8343363851]

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found")

# ==================== DATABASE SETUP ====================
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, 
                  join_date TEXT, is_banned BOOLEAN DEFAULT 0, credits INTEGER DEFAULT 10)''')
    
    # 2FA keys table
    c.execute('''CREATE TABLE IF NOT EXISTS totp_keys
                 (user_id INTEGER, secret_key TEXT, created_at TEXT)''')
    
    # Temp emails table
    c.execute('''CREATE TABLE IF NOT EXISTS temp_emails
                 (user_id INTEGER, email TEXT, created_at TEXT, last_checked TEXT)''')
    
    # Facebook checker logs
    c.execute('''CREATE TABLE IF NOT EXISTS fb_checks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                  phone_number TEXT, status TEXT, account_found BOOLEAN, 
                  otp_sent BOOLEAN, checked_at TEXT)''')
    
    # Virtual numbers table (admin managed)
    c.execute('''CREATE TABLE IF NOT EXISTS virtual_numbers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, country TEXT, 
                  is_available BOOLEAN DEFAULT 1, assigned_to INTEGER DEFAULT NULL,
                  assigned_at TEXT DEFAULT NULL)''')
    
    # User's current number
    c.execute('''CREATE TABLE IF NOT EXISTS user_numbers
                 (user_id INTEGER PRIMARY KEY, number_id INTEGER, number TEXT, 
                  country TEXT, assigned_at TEXT)''')
    
    conn.commit()
    conn.close()

init_db()

# ==================== HELPER FUNCTIONS ====================
def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_user_credits(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 10

def add_user(user_id, username, first_name):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, join_date, is_banned, credits) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, username or "", first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0, 10))
    conn.commit()
    conn.close()

def update_user_credits(user_id, amount):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

# ==================== MAIN MENU ====================
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Get Number", callback_data="get_number"),
         InlineKeyboardButton("📧 Get Tempmail", callback_data="get_tempmail")],
        [InlineKeyboardButton("🔐 2FA", callback_data="two_fa"),
         InlineKeyboardButton("💰 Balances", callback_data="balances")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw"),
         InlineKeyboardButton("🆘 Support", callback_data="support")]
    ])
    
    if is_admin(update.effective_user.id):
        keyboard.inline_keyboard.append([InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")])
    
    welcome_text = (
        "🤖 **Multi-Tool Bot**\n\n"
        "Select an option from the menu:\n\n"
        "📱 **Get Number** - Virtual phone numbers\n"
        "📧 **Get Tempmail** - Temporary email addresses\n"
        "🔐 **2FA** - Generate TOTP codes\n"
        "💰 **Balances** - Check your credits\n"
        "💸 **Withdraw** - Withdraw funds\n"
        "🆘 **Support** - Get help\n\n"
        f"💎 **Your Credits:** {get_user_credits(update.effective_user.id)}"
    )
    
    if query:
        await message.edit_text(welcome_text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=keyboard)

# ==================== VIRTUAL NUMBERS SECTION ====================
# _________________ VIRTUAL NUMBERS _________________

async def get_number_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 Get New Number", callback_data="assign_number")],
        [InlineKeyboardButton("🔄 Change Number", callback_data="change_number")],
        [InlineKeyboardButton("📋 My Current Number", callback_data="my_number")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        "📱 **Virtual Numbers**\n\n"
        "Get a virtual number for verifications.\n\n"
        "**Available Numbers:** {}\n\n"
        "Select an option below:".format(get_available_numbers_count()),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

def get_available_numbers_count():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM virtual_numbers WHERE is_available = 1")
    count = c.fetchone()[0]
    conn.close()
    return count

async def assign_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Check if user already has a number
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT number_id, number FROM user_numbers WHERE user_id = ?", (user_id,))
    existing = c.fetchone()
    
    if existing:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Change Number", callback_data="change_number")],
            [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
        ])
        await query.message.edit_text(
            f"❌ **You already have a number!**\n\n"
            f"Your current number: `{existing[1]}`\n\n"
            f"Use 'Change Number' to get a new one.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        conn.close()
        return
    
    # Get available number
    c.execute("SELECT id, number, country FROM virtual_numbers WHERE is_available = 1 LIMIT 1")
    available = c.fetchone()
    
    if not available:
        await query.message.edit_text(
            "❌ **No Numbers Available!**\n\n"
            "All numbers are currently assigned.\n"
            "Please try again later or contact admin.",
            parse_mode="Markdown"
        )
        conn.close()
        return
    
    number_id, number, country = available
    
    # Assign number to user
    c.execute("UPDATE virtual_numbers SET is_available = 0, assigned_to = ?, assigned_at = ? WHERE id = ?",
              (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), number_id))
    c.execute("INSERT OR REPLACE INTO user_numbers VALUES (?, ?, ?, ?, ?)",
              (user_id, number_id, number, country, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Change Number", callback_data="change_number")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        f"✅ **Number Assigned!**\n\n"
        f"📞 **Your Number:** `{number}`\n"
        f"🌍 **Country:** {country}\n\n"
        f"⚠️ This number can receive SMS for verifications.\n"
        f"Use 'Change Number' to get a different number.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def change_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # Get user's current number
    c.execute("SELECT number_id FROM user_numbers WHERE user_id = ?", (user_id,))
    current = c.fetchone()
    
    if current:
        # Free up the current number
        c.execute("UPDATE virtual_numbers SET is_available = 1, assigned_to = NULL, assigned_at = NULL WHERE id = ?", (current[0],))
        c.execute("DELETE FROM user_numbers WHERE user_id = ?", (user_id,))
    
    # Get new available number
    c.execute("SELECT id, number, country FROM virtual_numbers WHERE is_available = 1 LIMIT 1")
    available = c.fetchone()
    
    if not available:
        await query.message.edit_text(
            "❌ **No Numbers Available!**\n\n"
            "All numbers are currently assigned.\n"
            "Please try again later.",
            parse_mode="Markdown"
        )
        conn.close()
        return
    
    number_id, number, country = available
    
    # Assign new number
    c.execute("UPDATE virtual_numbers SET is_available = 0, assigned_to = ?, assigned_at = ? WHERE id = ?",
              (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), number_id))
    c.execute("INSERT OR REPLACE INTO user_numbers VALUES (?, ?, ?, ?, ?)",
              (user_id, number_id, number, country, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Change Again", callback_data="change_number")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        f"✅ **Number Changed!**\n\n"
        f"📞 **New Number:** `{number}`\n"
        f"🌍 **Country:** {country}\n\n"
        f"Use 'Change Number' to get another one.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def my_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT number, country, assigned_at FROM user_numbers WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📞 Get Number", callback_data="assign_number")],
            [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
        ])
        await query.message.edit_text(
            "❌ **No Number Assigned!**\n\n"
            "You don't have a virtual number yet.\n"
            "Click below to get one.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return
    
    number, country, assigned_at = result
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Change Number", callback_data="change_number")],
        [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
    ])
    
    await query.message.edit_text(
        f"📋 **Your Virtual Number**\n\n"
        f"📞 **Number:** `{number}`\n"
        f"🌍 **Country:** {country}\n"
        f"📅 **Assigned:** {assigned_at}\n\n"
        f"Use this number for verifications.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ==================== TEMP MAIL SECTION ====================
# _________________ TEMP MAIL _________________

temp_emails = {}

class TempMailAPI:
    domains = ['@tempmail.com', '@tempemail.net', '@guerrillamail.com', '@10minutemail.com']
    
    @staticmethod
    def create_email():
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        domain = random.choice(TempMailAPI.domains)
        return username + domain
    
    @staticmethod
    def get_inbox(email):
        messages = []
        if random.random() > 0.6:
            messages.append({
                'from': 'noreply@facebook.com',
                'subject': 'Your Facebook login code',
                'body': f'Your confirmation code is: {random.randint(100000, 999999)}',
                'time': datetime.now().strftime('%H:%M:%S')
            })
        return messages

async def get_tempmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id in temp_emails:
        email = temp_emails[user_id]['email']
        created = temp_emails[user_id]['created_at']
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Check Inbox", callback_data="check_inbox")],
            [InlineKeyboardButton("🔄 New Email", callback_data="new_tempmail")],
            [InlineKeyboardButton("🗑️ Delete Email", callback_data="delete_email")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
        ])
        
        await query.message.edit_text(
            f"📧 **Your Temporary Email**\n\n"
            f"`{email}`\n\n"
            f"📅 **Created:** {created}",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await create_new_tempmail(query)

async def create_new_tempmail(query):
    user_id = query.from_user.id
    email = TempMailAPI.create_email()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    temp_emails[user_id] = {
        'email': email,
        'created_at': created_at,
        'messages': []
    }
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Check Inbox", callback_data="check_inbox")],
        [InlineKeyboardButton("🔄 New Email", callback_data="new_tempmail")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="delete_email")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        f"📧 **Temporary Email Created!**\n\n"
        f"`{email}`\n\n"
        f"📅 **Created:** {created_at}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def check_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Checking inbox...")
    
    user_id = query.from_user.id
    
    if user_id not in temp_emails:
        await query.message.edit_text("No email found. Create one first!")
        return
    
    email = temp_emails[user_id]['email']
    messages = TempMailAPI.get_inbox(email)
    
    if not messages:
        inbox_text = f"📭 **Inbox Empty**\n\nNo new messages for `{email}`"
    else:
        inbox_text = f"📥 **Inbox - {email}**\n\n"
        for msg in messages[:5]:
            inbox_text += f"📧 **From:** {msg['from']}\n"
            inbox_text += f"📝 **Subject:** {msg['subject']}\n"
            inbox_text += f"💬 **Message:** {msg['body']}\n"
            inbox_text += f"🕐 **Time:** {msg['time']}\n"
            inbox_text += "─" * 20 + "\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="check_inbox")],
        [InlineKeyboardButton("🔙 Back", callback_data="get_tempmail")]
    ])
    
    await query.message.edit_text(inbox_text, parse_mode="Markdown", reply_markup=keyboard)

async def delete_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id in temp_emails:
        del temp_emails[user_id]
        
        await query.message.edit_text(
            "🗑️ **Email Deleted!**\n\n"
            "Your temporary email has been deleted.",
            parse_mode="Markdown"
        )
        
        await asyncio.sleep(2)
        await main_menu(update, context)

# ==================== 2FA SECTION ====================
# _________________ 2FA GENERATOR _________________

user_totp = {}

async def two_fa_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Add 2FA Key", callback_data="add_2fa")],
        [InlineKeyboardButton("📋 Generate OTP", callback_data="generate_otp")],
        [InlineKeyboardButton("🗑️ Remove Key", callback_data="remove_2fa")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        "🔐 **Two-Factor Authentication**\n\n"
        "Manage your TOTP keys here.\n\n"
        "**Features:**\n"
        "• Generate live OTP codes\n"
        "• 30-second countdown timer",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def add_2fa_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "🔑 **Add 2FA Key**\n\n"
        "Please send your TOTP secret key.\n\n"
        "**Example:** `JBSWY3DPEHPK3PXP`",
        parse_mode="Markdown"
    )
    
    context.user_data['awaiting_2fa_key'] = True
    return 1

async def handle_2fa_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_2fa_key'):
        return
    
    secret = update.message.text.strip().upper().replace(" ", "")
    
    try:
        totp = pyotp.TOTP(secret)
        test_otp = totp.now()
        if not test_otp or len(test_otp) != 6:
            raise ValueError("Invalid OTP generated")
        
        user_id = update.effective_user.id
        
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO totp_keys VALUES (?, ?, ?)",
                  (user_id, secret, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        
        user_totp[user_id] = {'totp': totp, 'secret': secret}
        
        await update.message.reply_text(
            "✅ **2FA Key Added Successfully!**\n\n"
            "Use /menu → 2FA → Generate OTP to get codes.",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Invalid Key!**\n\nError: {str(e)}",
            parse_mode="Markdown"
        )
    
    context.user_data['awaiting_2fa_key'] = False
    return ConversationHandler.END

async def generate_otp_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT secret_key FROM totp_keys WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        await query.message.edit_text(
            "❌ **No 2FA Key Found!**\n\n"
            "Please add a 2FA key first.",
            parse_mode="Markdown"
        )
        return
    
    secret = result[0]
    await generate_otp_display(query, secret)

async def generate_otp_display(query, secret):
    totp = pyotp.TOTP(secret)
    msg = await query.message.edit_text("⏳ Generating OTP...")
    
    while True:
        current_time = int(time.time())
        remaining = totp.interval - (current_time % totp.interval)
        otp = totp.at(current_time)
        
        progress = int((totp.interval - remaining) / totp.interval * 20)
        bar = "█" * progress + "░" * (20 - progress)
        
        text = (
            f"🔐 **Current OTP:**\n"
            f"```\n{otp}\n```\n\n"
            f"⏳ **Expires in:** `{remaining}s`\n"
            f"`{bar}`"
        )
        
        try:
            await msg.edit_text(text, parse_mode="Markdown")
        except:
            pass
        
        if remaining <= 1:
            break
        
        await asyncio.sleep(0.5)
    
    try:
        await msg.delete()
    except:
        pass
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Generate New OTP", callback_data="generate_otp")],
        [InlineKeyboardButton("🔙 2FA Menu", callback_data="two_fa")]
    ])
    
    await query.message.reply_text(
        "⌛ **OTP Expired!**\n\nClick below to generate a new code.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def remove_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("DELETE FROM totp_keys WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    if user_id in user_totp:
        del user_totp[user_id]
    
    await query.message.edit_text(
        "🗑️ **2FA Key Removed!**\n\n"
        "Your TOTP key has been deleted.",
        parse_mode="Markdown"
    )

# ==================== FACEBOOK CHECKER SECTION ====================
# _________________ FACEBOOK CHECKER _________________

class FacebookChecker:
    @staticmethod
    def check_account(phone_number):
        try:
            phone = ''.join(filter(str.isdigit, phone_number))
            if len(phone) < 10:
                return {'status': 'invalid', 'account_found': False, 'message': '❌ Invalid phone number'}
            
            last_digit = int(phone[-1])
            account_exists = (last_digit % 2 == 0)
            
            if account_exists:
                return {
                    'status': 'exists',
                    'account_found': True,
                    'message': '✅ Facebook account FOUND!',
                    'can_recover': True
                }
            else:
                return {
                    'status': 'not_exists',
                    'account_found': False,
                    'message': '❌ No Facebook account found',
                    'can_recover': False
                }
        except Exception as e:
            return {'status': 'error', 'account_found': False, 'message': f'Error: {str(e)}'}
    
    @staticmethod
    def send_recovery_otp(phone_number):
        mock_otp = ''.join(random.choices(string.digits, k=6))
        return {
            'success': True,
            'otp': mock_otp,
            'message': f'📱 OTP sent to {phone_number[:4]}****{phone_number[-4:]}'
        }

async def facebook_checker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Check Single Number", callback_data="fb_check_single")],
        [InlineKeyboardButton("🔍 Check + Send OTP", callback_data="fb_check_otp")],
        [InlineKeyboardButton("📈 Check History", callback_data="fb_history")],
        [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
    ])
    
    await query.message.edit_text(
        "📱 **Facebook Account Checker**\n\n"
        "⚠️ **DEMO MODE - Educational Purposes Only**\n\n"
        f"**Your Credits:** {get_user_credits(query.from_user.id)}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def fb_check_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    credits = get_user_credits(user_id)
    
    if credits < 1:
        await query.message.edit_text("❌ **Insufficient Credits!**", parse_mode="Markdown")
        return
    
    await query.message.edit_text(
        "📱 **Check Single Number**\n\n"
        "Send me the phone number to check:\n\n"
        "**Example:** `+8801712345678`\n\n"
        "⚠️ Cost: 1 credit"
    )
    
    context.user_data['awaiting_fb_check'] = 'single'
    return 1

async def fb_check_with_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    credits = get_user_credits(user_id)
    
    if credits < 2:
        await query.message.edit_text("❌ **Insufficient Credits!**", parse_mode="Markdown")
        return
    
    await query.message.edit_text(
        "📱 **Check + Send OTP**\n\n"
        "Send me the phone number:\n\n"
        "⚠️ Cost: 2 credits\n"
        "⚠️ This is a DEMO simulation"
    )
    
    context.user_data['awaiting_fb_check'] = 'with_otp'
    return 1

async def handle_fb_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'awaiting_fb_check' not in context.user_data:
        return
    
    check_type = context.user_data['awaiting_fb_check']
    phone = update.message.text.strip()
    user_id = update.effective_user.id
    
    cost = 2 if check_type == 'with_otp' else 1
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits - ? WHERE user_id = ?", (cost, user_id))
    conn.commit()
    conn.close()
    
    status_msg = await update.message.reply_text("🔍 Processing...")
    
    result = FacebookChecker.check_account(phone)
    
    response = f"📱 **Phone:** `{phone}`\n\n{result['message']}\n"
    
    if result['account_found'] and check_type == 'with_otp':
        await status_msg.edit_text("📨 Sending recovery OTP...")
        await asyncio.sleep(2)
        otp_result = FacebookChecker.send_recovery_otp(phone)
        response += f"\n{otp_result['message']}\n"
        if otp_result['success']:
            response += f"📱 **SIMULATED OTP:** `{otp_result['otp']}`\n"
            response += "\n⚠️ **This is a SIMULATION**"
        otp_sent = True
    else:
        otp_sent = False
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO fb_checks VALUES (?, ?, ?, ?, ?, ?, ?)",
              (None, user_id, phone, result['status'], 1 if result['account_found'] else 0,
               1 if otp_sent else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Check Another", callback_data="fb_check_single")],
        [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
    ])
    
    await status_msg.delete()
    await update.message.reply_text(response, parse_mode="Markdown", reply_markup=keyboard)
    
    context.user_data.pop('awaiting_fb_check', None)
    return ConversationHandler.END

async def fb_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT phone_number, account_found, checked_at FROM fb_checks WHERE user_id = ? ORDER BY checked_at DESC LIMIT 10", (user_id,))
    logs = c.fetchall()
    conn.close()
    
    if not logs:
        await query.message.edit_text("No check history found.")
        return
    
    history_text = "📊 **Your Check History**\n\n"
    for log in logs:
        phone, found, time = log
        history_text += f"📱 `{phone[:4]}****{phone[-4:]}` → {'✅ Found' if found else '❌ Not Found'}\n🕐 `{time}`\n\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
    ])
    
    await query.message.edit_text(history_text, parse_mode="Markdown", reply_markup=keyboard)

# ==================== BALANCES SECTION ====================
# _________________ BALANCES _________________

async def balances_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    credits = get_user_credits(user_id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        f"💰 **Your Balance**\n\n"
        f"💎 **Credits:** `{credits}`\n\n"
        f"**Credit Usage:**\n"
        f"• Facebook Check: 1 credit\n"
        f"• Facebook Check + OTP: 2 credits\n"
        f"• Virtual Number: Free\n"
        f"• Temp Email: Free\n"
        f"• 2FA Generator: Free",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ==================== WITHDRAW SECTION ====================
# _________________ WITHDRAW _________________

async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Request Withdrawal", callback_data="withdraw_request")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        "💸 **Withdraw Funds**\n\n"
        "**Minimum Withdrawal:** $10\n"
        "**Processing Time:** 24-48 hours\n\n"
        "**Available Methods:**\n"
        "• USDT (TRC20)\n"
        "• PayPal\n\n"
        "Contact admin to request withdrawal.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def withdraw_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "💰 **Request Withdrawal**\n\n"
        "Please contact @AdminUsername with:\n"
        "1. Amount\n"
        "2. Payment method\n"
        "3. Wallet address",
        parse_mode="Markdown"
    )

# ==================== SUPPORT SECTION ====================
# _________________ SUPPORT _________________

async def support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 FAQ", callback_data="faq")],
        [InlineKeyboardButton("👨‍💻 Contact Admin", url="https://t.me/YourUsername")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        "🆘 **Support Center**\n\n"
        "**Common Issues:**\n"
        "• 2FA not working? Check your secret key\n"
        "• Temp email not receiving? Wait a few minutes\n\n"
        "Need help? Contact our admin!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="support")]
    ])
    
    await query.message.edit_text(
        "📝 **FAQ**\n\n"
        "**Q: How to get 2FA codes?**\n"
        "A: Add your secret key in 2FA menu.\n\n"
        "**Q: How to earn credits?**\n"
        "A: Contact admin to purchase credits.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ==================== ADMIN PANEL SECTION ====================
# _________________ ADMIN PANEL _________________

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("➕ Add Number", callback_data="admin_add_number")],
        [InlineKeyboardButton("💰 Add Credits", callback_data="admin_add_credits")],
        [InlineKeyboardButton("📋 Number List", callback_data="admin_numbers")],
        [InlineKeyboardButton("📈 FB Logs", callback_data="admin_fb_logs")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        "🔧 **Admin Panel**\n\nSelect an option:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT SUM(credits) FROM users")
    total_credits = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM virtual_numbers WHERE is_available = 1")
    available_numbers = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM virtual_numbers WHERE is_available = 0")
    assigned_numbers = c.fetchone()[0]
    
    conn.close()
    
    stats_text = (
        "📊 **Bot Statistics**\n\n"
        f"👥 **Total Users:** `{total_users}`\n"
        f"💰 **Total Credits:** `{total_credits}`\n"
        f"📱 **Available Numbers:** `{available_numbers}`\n"
        f"📞 **Assigned Numbers:** `{assigned_numbers}`"
    )
    
    await query.message.edit_text(stats_text, parse_mode="Markdown")

async def admin_add_number_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text(
        "➕ **Add Virtual Number**\n\n"
        "Send the number in this format:\n"
        "`+1234567890,USA`\n\n"
        "Example: `+8801712345678,Bangladesh`"
    )
    
    context.user_data['awaiting_number'] = True
    return 1

async def admin_add_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_number'):
        return
    
    try:
        data = update.message.text.strip()
        parts = data.split(',')
        number = parts[0].strip()
        country = parts[1].strip() if len(parts) > 1 else "Unknown"
        
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT INTO virtual_numbers (number, country, is_available) VALUES (?, ?, ?)",
                  (number, country, 1))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Number added: `{number}` ({country})", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data.pop('awaiting_number', None)
    return ConversationHandler.END

async def admin_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT id, number, country, is_available, assigned_to FROM virtual_numbers ORDER BY id DESC LIMIT 20")
    numbers = c.fetchall()
    conn.close()
    
    if not numbers:
        await query.message.edit_text("No numbers found.")
        return
    
    text = "📋 **Number List**\n\n"
    for num in numbers:
        status = "✅ Available" if num[3] else f"❌ Assigned to {num[4]}"
        text += f"ID: {num[0]} | {num[1]} ({num[2]})\n{status}\n\n"
    
    await query.message.edit_text(text, parse_mode="Markdown")

async def admin_add_credits_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text(
        "💰 **Add Credits**\n\n"
        "Send in this format:\n"
        "`USER_ID AMOUNT`\n\n"
        "Example: `123456789 50`"
    )
    
    context.user_data['awaiting_credits'] = True
    return 1

async def admin_add_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_credits'):
        return
    
    try:
        parts = update.message.text.strip().split()
        user_id = int(parts[0])
        amount = int(parts[1])
        
        update_user_credits(user_id, amount)
        await update.message.reply_text(f"✅ Added {amount} credits to user {user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data.pop('awaiting_credits', None)
    return ConversationHandler.END

async def admin_fb_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT user_id, phone_number, account_found, checked_at FROM fb_checks ORDER BY checked_at DESC LIMIT 10")
    logs = c.fetchall()
    conn.close()
    
    if not logs:
        await query.message.edit_text("No logs found.")
        return
    
    text = "📈 **Recent FB Checks**\n\n"
    for log in logs:
        text += f"👤 User: {log[0]}\n📱 {log[1][:4]}****{log[1][-4:]}\n✅ {'Found' if log[2] else 'Not Found'}\n🕐 {log[3]}\n\n"
    
    await query.message.edit_text(text, parse_mode="Markdown")

# ==================== START & HELP COMMANDS ====================
# _________________ START & HELP _________________

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("menu", "Show main menu"),
        BotCommand("help", "Help"),
        BotCommand("myid", "Get user ID"),
    ]
    await context.bot.set_my_commands(commands)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Open Menu", callback_data="main_menu")]
    ])
    
    await update.message.reply_text(
        f"👋 Welcome {user.first_name}!\n\n"
        f"🤖 **Multi-Tool Bot**\n\n"
        f"I can help you with:\n"
        f"✓ Virtual Numbers\n"
        f"✓ Temporary Email\n"
        f"✓ 2FA Code Generator\n"
        f"✓ Facebook Account Checker (DEMO)\n\n"
        f"💎 You have 10 free credits!\n\n"
        f"Click the button below to get started!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu(update, context)

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 **Your ID:** `{user.id}`\n"
        f"👤 **Username:** @{user.username or 'None'}\n"
        f"💎 **Credits:** {get_user_credits(user.id)}",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **Help Guide**\n\n"
        "**Commands:**\n"
        "/start - Start bot\n"
        "/menu - Show menu\n"
        "/myid - Get user ID\n"
        "/help - This message\n\n"
        "**Features:**\n"
        "📱 Get Number - Virtual numbers\n"
        "📧 Get Tempmail - Temp email\n"
        "🔐 2FA - OTP codes\n"
        "💰 Balances - Check credits"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ==================== MAIN FUNCTION ====================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Conversation handlers
    fb_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(fb_check_single, pattern="fb_check_single"),
            CallbackQueryHandler(fb_check_with_otp, pattern="fb_check_otp")
        ],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fb_check)]},
        fallbacks=[]
    )
    
    twofa_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_2fa_prompt, pattern="add_2fa")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_2fa_key)]},
        fallbacks=[]
    )
    
    admin_number_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_number_prompt, pattern="admin_add_number")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_number)]},
        fallbacks=[]
    )
    
    admin_credits_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_credits_prompt, pattern="admin_add_credits")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_credits)]},
        fallbacks=[]
    )
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("help", help_command))
    
    # Main menu handlers
    app.add_handler(CallbackQueryHandler(main_menu, pattern="main_menu"))
    app.add_handler(CallbackQueryHandler(get_number_menu, pattern="get_number"))
    app.add_handler(CallbackQueryHandler(get_tempmail, pattern="get_tempmail"))
    app.add_handler(CallbackQueryHandler(two_fa_menu, pattern="two_fa"))
    app.add_handler(CallbackQueryHandler(balances_menu, pattern="balances"))
    app.add_handler(CallbackQueryHandler(withdraw_menu, pattern="withdraw"))
    app.add_handler(CallbackQueryHandler(support_menu, pattern="support"))
    
    # Number handlers
    app.add_handler(CallbackQueryHandler(assign_number, pattern="assign_number"))
    app.add_handler(CallbackQueryHandler(change_number, pattern="change_number"))
    app.add_handler(CallbackQueryHandler(my_number, pattern="my_number"))
    
    # Temp mail handlers
    app.add_handler(CallbackQueryHandler(create_new_tempmail, pattern="new_tempmail"))
    app.add_handler(CallbackQueryHandler(check_inbox, pattern="check_inbox"))
    app.add_handler(CallbackQueryHandler(delete_email, pattern="delete_email"))
    
    # 2FA handlers
    app.add_handler(CallbackQueryHandler(generate_otp_menu, pattern="generate_otp"))
    app.add_handler(CallbackQueryHandler(remove_2fa, pattern="remove_2fa"))
    
    # Facebook handlers
    app.add_handler(CallbackQueryHandler(facebook_checker_menu, pattern="fb_checker"))
    app.add_handler(CallbackQueryHandler(fb_history, pattern="fb_history"))
    
    # Withdraw handlers
    app.add_handler(CallbackQueryHandler(withdraw_request, pattern="withdraw_request"))
    
    # Support handlers
    app.add_handler(CallbackQueryHandler(faq, pattern="faq"))
    
    # Admin handlers
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="admin_panel"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="admin_stats"))
    app.add_handler(CallbackQueryHandler(admin_numbers, pattern="admin_numbers"))
    app.add_handler(CallbackQueryHandler(admin_fb_logs, pattern="admin_fb_logs"))
    
    # Conversation handlers
    app.add_handler(fb_conv_handler)
    app.add_handler(twofa_conv_handler)
    app.add_handler(admin_number_handler)
    app.add_handler(admin_credits_handler)
    
    print("=" * 50)
    print("🤖 Multi-Tool Bot is running!")
    print("=" * 50)
    print("📱 Features:")
    print("   • Virtual Numbers (Admin can add numbers via TXT)")
    print("   • Temporary Email")
    print("   • 2FA Code Generator")
    print("   • Facebook Checker (DEMO)")
    print("   • Balance & Withdraw System")
    print("=" * 50)
    print(f"👑 Admin IDs: {ADMIN_IDS}")
    print("=" * 50)
    print("Press Ctrl+C to stop")
    
    app.run_polling()

if __name__ == "__main__":
    main()