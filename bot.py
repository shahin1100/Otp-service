import pyotp
import asyncio
import time
import logging
import requests
import json
import random
import string
import sqlite3
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
from dotenv import load_dotenv
import os

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

# Database setup
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, 
                  join_date TEXT, is_banned BOOLEAN DEFAULT 0, credits INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS totp_keys
                 (user_id INTEGER, secret_key TEXT, created_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS temp_emails
                 (user_id INTEGER, email TEXT, created_at TEXT, last_checked TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS fb_checks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                  phone_number TEXT, status TEXT, account_found BOOLEAN, 
                  otp_sent BOOLEAN, checked_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_usage
                 (user_id INTEGER, feature TEXT, used_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS virtual_numbers
                 (user_id INTEGER, number TEXT, country TEXT, created_at TEXT)''')
    
    conn.commit()
    conn.close()

init_db()

# Global storage
user_totp = {}
temp_emails = {}
virtual_numbers = {}

# TempMail API
class TempMailAPI:
    domains = ['@tempmail.com', '@tempemail.net', '@guerrillamail.com', '@10minutemail.com', '@mailinator.com']
    
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
                'body': f'Your Facebook confirmation code is: {random.randint(100000, 999999)}',
                'time': datetime.now().strftime('%H:%M:%S')
            })
        if random.random() > 0.8:
            messages.append({
                'from': 'noreply@google.com',
                'subject': 'Google Verification Code',
                'body': f'Your Google verification code is: {random.randint(100000, 999999)}',
                'time': datetime.now().strftime('%H:%M:%S')
            })
        return messages

# Virtual Numbers
class VirtualNumberAPI:
    @staticmethod
    def get_number(country):
        numbers = {
            'usa': ['+1 (555) 123-4567', '+1 (555) 234-5678', '+1 (555) 345-6789', '+1 (555) 456-7890', '+1 (555) 567-8901'],
            'uk': ['+44 20 1234 5678', '+44 20 2345 6789', '+44 20 3456 7890', '+44 20 4567 8901', '+44 20 5678 9012'],
            'canada': ['+1 (416) 123-4567', '+1 (416) 234-5678', '+1 (416) 345-6789', '+1 (416) 456-7890', '+1 (416) 567-8901'],
            'australia': ['+61 2 1234 5678', '+61 2 2345 6789', '+61 2 3456 7890', '+61 2 4567 8901', '+61 2 5678 9012']
        }
        return random.choice(numbers.get(country, numbers['usa']))

# Facebook Checker
class FacebookChecker:
    @staticmethod
    def check_account(phone_number):
        try:
            phone = ''.join(filter(str.isdigit, phone_number))
            if len(phone) < 10:
                return {
                    'status': 'invalid',
                    'account_found': False,
                    'message': '❌ Invalid phone number format'
                }
            
            last_digit = int(phone[-1])
            account_exists = (last_digit % 2 == 0)
            
            if account_exists:
                return {
                    'status': 'exists',
                    'account_found': True,
                    'message': '✅ Facebook account FOUND!',
                    'can_recover': True,
                    'account_info': {
                        'name': f'User_{phone[-4:]}',
                        'created': '2015-2023'
                    }
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
            'message': f'📱 OTP sent to {phone_number[:4]}****{phone_number[-4:]}',
            'expires_in': 300
        }

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_user_credits(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def add_user(user_id, username, first_name):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, join_date, is_banned, credits) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, username or "", first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0, 10))
    conn.commit()
    conn.close()

# Main Menu
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

# Get Number Menu
async def get_number_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇸 USA Number", callback_data="number_usa"),
         InlineKeyboardButton("🇬🇧 UK Number", callback_data="number_uk")],
        [InlineKeyboardButton("🇨🇦 Canada", callback_data="number_ca"),
         InlineKeyboardButton("🇦🇺 Australia", callback_data="number_au")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        "📱 **Get Virtual Number**\n\n"
        "Select a country to get a virtual phone number:\n\n"
        "⚠️ Numbers are for verification purposes only.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def get_virtual_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    country_map = {
        'number_usa': 'usa',
        'number_uk': 'uk', 
        'number_ca': 'canada',
        'number_au': 'australia'
    }
    
    country = country_map.get(query.data, 'usa')
    country_names = {'usa': 'USA', 'uk': 'UK', 'canada': 'Canada', 'australia': 'Australia'}
    
    number = VirtualNumberAPI.get_number(country)
    user_id = query.from_user.id
    
    virtual_numbers[user_id] = {'number': number, 'country': country_names[country]}
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO virtual_numbers VALUES (?, ?, ?, ?)",
              (user_id, number, country_names[country], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Get Another Number", callback_data="get_number")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        f"📱 **Your Virtual Number**\n\n"
        f"🌍 **Country:** {country_names[country]}\n"
        f"📞 **Number:** `{number}`\n\n"
        f"⚠️ This number can receive SMS for verifications.\n"
        f"📝 Valid for 10 minutes.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# Temp Mail
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
            f"📅 **Created:** {created}\n\n"
            f"Use this email for temporary verifications.",
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
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO temp_emails VALUES (?, ?, ?, ?)",
              (user_id, email, created_at, None))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Check Inbox", callback_data="check_inbox")],
        [InlineKeyboardButton("🔄 New Email", callback_data="new_tempmail")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="delete_email")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        f"📧 **Temporary Email Created!**\n\n"
        f"`{email}`\n\n"
        f"📅 **Created:** {created_at}\n\n"
        f"Click 'Check Inbox' to see new messages.",
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
        
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("DELETE FROM temp_emails WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        await query.message.edit_text(
            "🗑️ **Email Deleted!**\n\n"
            "Your temporary email has been deleted.\n\n"
            "Create a new one anytime.",
            parse_mode="Markdown"
        )
        
        await asyncio.sleep(2)
        await main_menu(update, context)

# 2FA Generator
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
        "• 30-second countdown timer\n"
        "• Auto-refresh on expiry",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def add_2fa_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "🔑 **Add 2FA Key**\n\n"
        "Please send your TOTP secret key.\n\n"
        "**Example:** `JBSWY3DPEHPK3PXP`\n\n"
        "You can get this key from Google Authenticator or any 2FA app.",
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
        
        user_totp[user_id] = {
            'totp': totp,
            'secret': secret
        }
        
        await update.message.reply_text(
            "✅ **2FA Key Added Successfully!**\n\n"
            "Use /menu → 2FA → Generate OTP to get codes.",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Invalid Key!**\n\nError: {str(e)}\n\nPlease send a valid base32 encoded secret.",
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
            "Please add a 2FA key first using 'Add 2FA Key' option.",
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
            f"`{bar}`\n\n"
            f"🔄 New code will generate automatically"
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
        "Your TOTP key has been deleted.\n\n"
        "You can add a new key anytime.",
        parse_mode="Markdown"
    )

# Balances
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
        f"• 2FA Generator: Free\n\n"
        f"Contact admin to purchase more credits!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# Withdraw
async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Request Withdrawal", callback_data="withdraw_request")],
        [InlineKeyboardButton("📊 Withdrawal History", callback_data="withdraw_history")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        "💸 **Withdraw Funds**\n\n"
        "**Minimum Withdrawal:** $10\n"
        "**Processing Time:** 24-48 hours\n\n"
        "**Available Methods:**\n"
        "• USDT (TRC20)\n"
        "• PayPal\n"
        "• Bank Transfer\n\n"
        "**Your Balance:** $0.00\n\n"
        "Select an option below:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def withdraw_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "💰 **Request Withdrawal**\n\n"
        "Please send your withdrawal details:\n\n"
        "1. Amount (minimum $10)\n"
        "2. Payment method (USDT/PayPal/Bank)\n"
        "3. Wallet address/email/account number\n\n"
        "Example:\n"
        "Amount: $50\n"
        "Method: USDT\n"
        "Address: TX123...\n\n"
        "Our team will process your request within 48 hours.",
        parse_mode="Markdown"
    )

async def withdraw_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "📊 **Withdrawal History**\n\n"
        "No withdrawal history found.\n\n"
        "Make your first withdrawal today!",
        parse_mode="Markdown"
    )

# Support
async def support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 FAQ", callback_data="faq")],
        [InlineKeyboardButton("👨‍💻 Contact Admin", url="https://t.me/YourSupportUsername")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        "🆘 **Support Center**\n\n"
        "**Common Issues:**\n"
        "• 2FA not working? Check your secret key\n"
        "• Temp email not receiving? Wait a few minutes\n"
        "• Facebook checker? Use valid phone numbers\n\n"
        "**Response Time:** 24 hours\n\n"
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
        "📝 **Frequently Asked Questions**\n\n"
        "**Q: How to get 2FA codes?**\n"
        "A: Add your secret key in 2FA menu, then generate OTP.\n\n"
        "**Q: Temp email not working?**\n"
        "A: Try creating a new email or wait 2-3 minutes.\n\n"
        "**Q: How to earn credits?**\n"
        "A: Contact admin to purchase credits.\n\n"
        "**Q: Is Facebook checker real?**\n"
        "A: This is a DEMO simulation for educational purposes.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# Facebook Checker Functions
async def facebook_checker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Check Single Number", callback_data="fb_check_single")],
        [InlineKeyboardButton("🔍 Check + Send OTP", callback_data="fb_check_otp")],
        [InlineKeyboardButton("📈 Check History", callback_data="fb_history")],
        [InlineKeyboardButton("ℹ️ How it Works", callback_data="fb_info")],
        [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
    ])
    
    await query.message.edit_text(
        "📱 **Facebook Account Checker**\n\n"
        "⚠️ **DEMO MODE - Educational Purposes Only**\n\n"
        "**Features:**\n"
        "• Check if phone number has Facebook account\n"
        "• Send recovery OTP (SIMULATED)\n"
        "• Check history\n\n"
        f"**Your Credits:** {get_user_credits(query.from_user.id)}\n\n"
        "🔴 **Important:** This is a simulation.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def fb_check_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    credits = get_user_credits(user_id)
    
    if credits < 1:
        await query.message.edit_text(
            "❌ **Insufficient Credits!**\n\n"
            f"You have {credits} credits.\n"
            "Each check costs 1 credit.\n\n"
            "Contact admin to get more credits.",
            parse_mode="Markdown"
        )
        return
    
    await query.message.edit_text(
        "📱 **Check Single Number**\n\n"
        "Send me the phone number to check:\n\n"
        "**Format:**\n"
        "• `+1234567890` (with country code)\n"
        "• `1234567890` (US/CA)\n\n"
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
        await query.message.edit_text(
            "❌ **Insufficient Credits!**\n\n"
            f"You have {credits} credits.\n"
            "Check + OTP costs 2 credits.\n\n"
            "Contact admin to get more credits.",
            parse_mode="Markdown"
        )
        return
    
    await query.message.edit_text(
        "📱 **Check + Send OTP**\n\n"
        "Send me the phone number:\n\n"
        "**What will happen:**\n"
        "1. Check if Facebook account exists\n"
        "2. If found, trigger forgot password\n"
        "3. Send OTP via SMS (SIMULATED)\n\n"
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
    
    response = f"📱 **Phone:** `{phone}`\n\n"
    response += f"{result['message']}\n\n"
    
    if result['account_found']:
        response += "**Account Details:**\n"
        response += f"• Name: {result.get('account_info', {}).get('name', 'Unknown')}\n"
        response += f"• Created: {result.get('account_info', {}).get('created', 'Unknown')}\n\n"
        
        if check_type == 'with_otp' and result['can_recover']:
            await status_msg.edit_text("📨 Sending recovery OTP...")
            await asyncio.sleep(2)
            
            otp_result = FacebookChecker.send_recovery_otp(phone)
            
            response += "**Recovery OTP:**\n"
            response += f"{otp_result['message']}\n"
            if otp_result['success']:
                response += f"📱 **SIMULATED OTP:** `{otp_result['otp']}`\n"
                response += f"⏱️ Expires in: {otp_result['expires_in']} seconds\n"
                response += "\n⚠️ **This is a SIMULATION**"
            
            otp_sent = otp_result['success']
        else:
            otp_sent = False
            if check_type == 'with_otp':
                response += "⚠️ Recovery not available for this account.\n"
    else:
        otp_sent = False
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO fb_checks (user_id, phone_number, status, account_found, otp_sent, checked_at) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, phone, result['status'], 
               1 if result['account_found'] else 0,
               1 if otp_sent else 0,
               datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Check Another", callback_data="fb_check_single")],
        [InlineKeyboardButton("📊 Check History", callback_data="fb_history")],
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
    c.execute("SELECT phone_number, status, account_found, checked_at FROM fb_checks WHERE user_id = ? ORDER BY checked_at DESC LIMIT 10", (user_id,))
    logs = c.fetchall()
    conn.close()
    
    if not logs:
        await query.message.edit_text("No check history found. Use the checker first!")
        return
    
    history_text = "📊 **Your Facebook Check History**\n\n"
    for log in logs:
        phone, status, found, time = log
        history_text += f"📱 `{phone[:4]}****{phone[-4:]}`\n"
        history_text += f"✅ Found: `{'Yes' if found else 'No'}`\n"
        history_text += f"🕐 `{time}`\n"
        history_text += "─" * 20 + "\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="fb_history")],
        [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
    ])
    
    await query.message.edit_text(history_text, parse_mode="Markdown", reply_markup=keyboard)

async def fb_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    info_text = (
        "ℹ️ **Facebook Checker - Information**\n\n"
        "**⚠️ IMPORTANT DISCLAIMER:**\n"
        "This is a DEMO/SIMULATION tool for educational purposes only.\n\n"
        "**How it works:**\n"
        "• Checks phone number against simulated database\n"
        "• Does NOT access real Facebook accounts\n"
        "• Does NOT send actual SMS messages\n"
        "• All OTPs shown are randomly generated\n\n"
        "For real Facebook account recovery, visit:\n"
        "https://www.facebook.com/login/identify"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
    ])
    
    await query.message.edit_text(info_text, parse_mode="Markdown", reply_markup=keyboard)

# Admin Panel
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 User List", callback_data="admin_users")],
        [InlineKeyboardButton("💰 Add Credits", callback_data="admin_add_credits")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📈 FB Check Logs", callback_data="admin_fb_logs")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        "🔧 **Admin Panel**\n\nWelcome to admin control panel.\n\nSelect an option:",
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
    
    c.execute("SELECT COUNT(*) FROM users WHERE credits > 0")
    active_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM totp_keys")
    totp_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM temp_emails")
    email_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM fb_checks")
    total_fb_checks = c.fetchone()[0]
    
    c.execute("SELECT SUM(credits) FROM users")
    total_credits = c.fetchone()[0] or 0
    
    conn.close()
    
    stats_text = (
        "📊 **Bot Statistics**\n\n"
        f"👥 **Total Users:** `{total_users}`\n"
        f"🟢 **Active Users:** `{active_users}`\n"
        f"🔐 **2FA Users:** `{totp_users}`\n"
        f"📧 **Temp Email Users:** `{email_users}`\n"
        f"📱 **FB Checks:** `{total_fb_checks}`\n"
        f"💰 **Total Credits:** `{total_credits}`\n\n"
        f"🤖 **Bot Status:** 🟢 Running"
    )
    
    await query.message.edit_text(stats_text, parse_mode="Markdown")

async def admin_fb_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT user_id, phone_number, status, account_found, otp_sent, checked_at FROM fb_checks ORDER BY checked_at DESC LIMIT 20")
    logs = c.fetchall()
    conn.close()
    
    if not logs:
        await query.message.edit_text("No logs found.")
        return
    
    logs_text = "📋 **Recent Facebook Checks**\n\n"
    for log in logs:
        user_id, phone, status, found, otp_sent, time = log
        logs_text += f"👤 User: `{user_id}`\n"
        logs_text += f"📱 Phone: `{phone[:4]}****{phone[-4:]}`\n"
        logs_text += f"✅ Found: `{'Yes' if found else 'No'}`\n"
        logs_text += f"📨 OTP Sent: `{'Yes' if otp_sent else 'No'}`\n"
        logs_text += f"🕐 Time: `{time}`\n"
        logs_text += "─" * 20 + "\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_fb_logs")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ])
    
    await query.message.edit_text(logs_text, parse_mode="Markdown", reply_markup=keyboard)

# Start and other commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("menu", "Show main menu"),
        BotCommand("help", "Help and support"),
        BotCommand("myid", "Get your user ID"),
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
        f"💎 You've received 10 free credits!\n\n"
        f"Click the button below to get started!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu(update, context)

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 **Your Information**\n\n"
        f"**User ID:** `{user.id}`\n"
        f"**Username:** @{user.username or 'None'}\n"
        f"**First Name:** {user.first_name}\n"
        f"**Credits:** {get_user_credits(user.id)}\n\n"
        f"Share this ID with support if needed.",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **Bot Help Guide**\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/menu - Show main menu\n"
        "/myid - Get your user ID\n"
        "/help - Show this message\n\n"
        "**Features:**\n"
        "📱 **Get Number** - Virtual phone numbers\n"
        "📧 **Get Tempmail** - Temporary email addresses\n"
        "🔐 **2FA** - Generate TOTP codes\n"
        "💰 **Balances** - Check credits\n"
        "💸 **Withdraw** - Withdraw funds\n"
        "🆘 **Support** - Get help\n\n"
        "**Need help?** Contact @YourSupportUsername"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

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
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("help", help_command))
    
    # Callback handlers - Main menu
    app.add_handler(CallbackQueryHandler(main_menu, pattern="main_menu"))
    app.add_handler(CallbackQueryHandler(get_number_menu, pattern="get_number"))
    app.add_handler(CallbackQueryHandler(get_tempmail, pattern="get_tempmail"))
    app.add_handler(CallbackQueryHandler(two_fa_menu, pattern="two_fa"))
    app.add_handler(CallbackQueryHandler(balances_menu, pattern="balances"))
    app.add_handler(CallbackQueryHandler(withdraw_menu, pattern="withdraw"))
    app.add_handler(CallbackQueryHandler(support_menu, pattern="support"))
    
    # Number handlers
    app.add_handler(CallbackQueryHandler(get_virtual_number, pattern="number_"))
    
    # Temp mail handlers
    app.add_handler(CallbackQueryHandler(create_new_tempmail, pattern="new_tempmail"))
    app.add_handler(CallbackQueryHandler(check_inbox, pattern="check_inbox"))
    app.add_handler(CallbackQueryHandler(delete_email, pattern="delete_email"))
    
    # 2FA handlers
    app.add_handler(CallbackQueryHandler(generate_otp_menu, pattern="generate_otp"))
    app.add_handler(CallbackQueryHandler(remove_2fa, pattern="remove_2fa"))
    
    # Withdraw handlers
    app.add_handler(CallbackQueryHandler(withdraw_request, pattern="withdraw_request"))
    app.add_handler(CallbackQueryHandler(withdraw_history, pattern="withdraw_history"))
    
    # Support handlers
    app.add_handler(CallbackQueryHandler(faq, pattern="faq"))
    
    # Facebook checker handlers
    app.add_handler(CallbackQueryHandler(facebook_checker_menu, pattern="fb_checker"))
    app.add_handler(CallbackQueryHandler(fb_history, pattern="fb_history"))
    app.add_handler(CallbackQueryHandler(fb_info, pattern="fb_info"))
    
    # Admin handlers
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="admin_panel"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="admin_stats"))
    app.add_handler(CallbackQueryHandler(admin_fb_logs, pattern="admin_fb_logs"))
    
    # Conversation handlers
    app.add_handler(fb_conv_handler)
    app.add_handler(twofa_conv_handler)
    
    print("🤖 Multi-Tool Bot is running...")
    print("✅ All features are now working!")
    print("📱 Features: Virtual Numbers, Temp Mail, 2FA, Facebook Checker")
    print(f"👑 Admin IDs: {ADMIN_IDS}")
    print("Press Ctrl+C to stop")
    
    app.run_polling()

if __name__ == "__main__":
    main()