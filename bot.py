"""
Multi-Tool Telegram Bot - Complete Version
Features: Facebook Checker, 2FA, Temp Mail, Credit System, Admin Panel
"""

import pyotp
import asyncio
import logging
import requests
import json
import random
import string
import sqlite3
import re
import hashlib
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler, 
    CallbackQueryHandler, ContextTypes, filters, ConversationHandler
)
import os

# ==================== CONFIGURATION ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8343363851:AAET2wh52oAgXrGEd_IDCEdfZNUUzQ7rNKM")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "8343363851").split(",")] if os.environ.get("ADMIN_IDS") else [8343363851]

# ==================== DATABASE SETUP ====================
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        join_date TEXT,
        is_banned INTEGER DEFAULT 0,
        credits INTEGER DEFAULT 10,
        total_spent INTEGER DEFAULT 0,
        referral_code TEXT,
        referred_by INTEGER,
        last_active TEXT
    )''')
    
    # 2FA keys table
    c.execute('''CREATE TABLE IF NOT EXISTS totp_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        service_name TEXT,
        secret_key TEXT,
        created_at TEXT,
        last_used TEXT,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')
    
    # Temp emails table
    c.execute('''CREATE TABLE IF NOT EXISTS temp_emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        email TEXT,
        created_at TEXT,
        expires_at TEXT,
        last_checked TEXT,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')
    
    # Email messages table
    c.execute('''CREATE TABLE IF NOT EXISTS email_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email_id INTEGER,
        sender TEXT,
        subject TEXT,
        body TEXT,
        received_at TEXT,
        is_read INTEGER DEFAULT 0,
        FOREIGN KEY(email_id) REFERENCES temp_emails(id)
    )''')
    
    # Facebook checker logs
    c.execute('''CREATE TABLE IF NOT EXISTS fb_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        phone_number TEXT,
        status TEXT,
        account_found INTEGER DEFAULT 0,
        otp_sent INTEGER DEFAULT 0,
        otp_code TEXT,
        checked_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')
    
    # Transactions table
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        type TEXT,
        description TEXT,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')
    
    # Broadcast history
    c.execute('''CREATE TABLE IF NOT EXISTS broadcasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        message TEXT,
        sent_to INTEGER,
        created_at TEXT
    )''')
    
    # Support tickets
    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        subject TEXT,
        message TEXT,
        status TEXT DEFAULT 'open',
        created_at TEXT,
        closed_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')
    
    # Withdraw requests
    c.execute('''CREATE TABLE IF NOT EXISTS withdraw_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        method TEXT,
        address TEXT,
        status TEXT DEFAULT 'pending',
        requested_at TEXT,
        processed_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')
    
    conn.commit()
    conn.close()

init_db()

# ==================== UTILITY FUNCTIONS ====================
def get_user_credits(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def update_user_credits(user_id, amount, transaction_type, description):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))
    c.execute("INSERT INTO transactions (user_id, amount, type, description, created_at) VALUES (?, ?, ?, ?, ?)",
              (user_id, amount, transaction_type, description, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def is_admin(user_id):
    return user_id in ADMIN_IDS

def generate_referral_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# ==================== FACEBOOK CHECKER (DEMO) ====================
class FacebookChecker:
    @staticmethod
    def check_account(phone_number):
        """SIMULATION - Educational purposes only"""
        try:
            phone = ''.join(filter(str.isdigit, phone_number))
            if len(phone) < 10:
                return {'status': 'invalid', 'account_found': False, 'message': '❌ Invalid phone number!'}
            
            # Demo logic
            last_digit = int(phone[-1])
            account_exists = last_digit % 2 == 0
            
            if account_exists:
                return {
                    'status': 'exists',
                    'account_found': True,
                    'message': '✅ Facebook account FOUND!',
                    'can_recover': True,
                    'account_info': {
                        'name': f'User_{phone[-4:]}',
                        'created': '2015-2023',
                        'last_active': 'Recently',
                        'profile_url': f'https://facebook.com/profile_{phone[-6:]}'
                    }
                }
            else:
                return {'status': 'not_exists', 'account_found': False, 'message': '❌ No Facebook account found.'}
        except Exception as e:
            return {'status': 'error', 'account_found': False, 'message': f'⚠️ Error: {str(e)}'}
    
    @staticmethod
    def send_recovery_otp(phone_number):
        """SIMULATION - Educational purposes only"""
        try:
            mock_otp = ''.join(random.choices(string.digits, k=6))
            return {'success': True, 'otp': mock_otp, 'message': f'📱 SIMULATED OTP: {mock_otp}'}
        except Exception as e:
            return {'success': False, 'message': f'Failed: {str(e)}'}

# ==================== TEMP MAIL SERVICE ====================
class TempMailService:
    @staticmethod
    def generate_email():
        """Generate temporary email address"""
        domains = ['tempmail.com', 'tempinbox.com', '10minute.com', 'throwaway.com']
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        email = f"{username}@{random.choice(domains)}"
        return email
    
    @staticmethod
    def create_temp_email(user_id):
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        
        email = TempMailService.generate_email()
        expires_at = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("INSERT INTO temp_emails (user_id, email, created_at, expires_at, last_checked, is_active) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, email, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expires_at, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 1))
        conn.commit()
        conn.close()
        return email
    
    @staticmethod
    def get_user_emails(user_id):
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT id, email, created_at, expires_at, is_active FROM temp_emails WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC", (user_id,))
        emails = c.fetchall()
        conn.close()
        return emails

# ==================== 2FA MANAGER ====================
class TwoFAManager:
    @staticmethod
    def add_secret(user_id, service_name, secret_key):
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT INTO totp_keys (user_id, service_name, secret_key, created_at, last_used) VALUES (?, ?, ?, ?, ?)",
                  (user_id, service_name, secret_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        return True
    
    @staticmethod
    def get_user_services(user_id):
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT id, service_name, secret_key, created_at FROM totp_keys WHERE user_id = ?", (user_id,))
        services = c.fetchall()
        conn.close()
        return services
    
    @staticmethod
    def generate_code(secret_key):
        try:
            totp = pyotp.TOTP(secret_key)
            return totp.now()
        except:
            return None

# ==================== BOT COMMAND HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Check if user exists
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user.id,))
    existing = c.fetchone()
    
    if not existing:
        referral_code = generate_referral_code()
        c.execute("INSERT INTO users (user_id, username, first_name, last_name, join_date, credits, referral_code, last_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (user.id, user.username or "", user.first_name or "", user.last_name or "", 
                   datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 10, referral_code, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        
        # Handle referral
        args = context.args
        if args and len(args) > 0:
            ref_code = args[0]
            c.execute("SELECT user_id FROM users WHERE referral_code = ?", (ref_code,))
            referrer = c.fetchone()
            if referrer:
                c.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer[0], user.id))
                update_user_credits(referrer[0], 5, 'referral', f'Referred user {user.id}')
                update_user_credits(user.id, 5, 'bonus', 'Welcome bonus from referral')
        
        conn.commit()
    
    conn.close()
    
    # Set bot commands
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("menu", "Show main menu"),
        BotCommand("myid", "Get your user ID"),
        BotCommand("credits", "Check your credits"),
        BotCommand("refer", "Get referral link"),
        BotCommand("help", "Help and support"),
    ]
    await context.bot.set_my_commands(commands)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Facebook Checker", callback_data="fb_checker"),
         InlineKeyboardButton("🔐 2FA Generator", callback_data="two_fa")],
        [InlineKeyboardButton("📧 Temp Mail", callback_data="temp_mail"),
         InlineKeyboardButton("💰 My Credits", callback_data="show_credits")],
        [InlineKeyboardButton("📊 Referral Program", callback_data="referral"),
         InlineKeyboardButton("💸 Withdraw", callback_data="withdraw_menu")],
        [InlineKeyboardButton("🆘 Support", callback_data="support"),
         InlineKeyboardButton("ℹ️ Help", callback_data="help_menu")],
    ])
    
    if is_admin(user.id):
        keyboard.inline_keyboard.append([InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")])
    
    welcome_text = f"""
🌟 **Welcome to Multi-Tool Bot!** 🌟

Hello {user.first_name}! 👋

**Available Features:**
📱 **Facebook Checker** - Check Facebook accounts (Demo)
🔐 **2FA Generator** - Generate TOTP codes
📧 **Temp Mail** - Temporary email addresses
💰 **Credit System** - Earn and use credits
📊 **Referral Program** - Earn 5 credits per referral

💎 **Your Credits:** {get_user_credits(user.id)}

Use the buttons below to get started! 🚀
"""
    
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=keyboard)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    credits = get_user_credits(user.id)
    
    text = f"""
🆔 **Your Information**

**User ID:** `{user.id}`
**Username:** @{user.username or 'None'}
**First Name:** {user.first_name or 'None'}
**Credits:** {credits}

Share this ID with support if needed.
"""
    await update.message.reply_text(text, parse_mode="Markdown")

async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    credits = get_user_credits(user_id)
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT amount, type, description, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (user_id,))
    transactions = c.fetchall()
    conn.close()
    
    text = f"💰 **Your Balance**\n\n💎 Credits: `{credits}`\n\n**Recent Transactions:**\n"
    
    if transactions:
        for trans in transactions:
            amount, trans_type, desc, time = trans
            sign = "+" if amount > 0 else ""
            text += f"• {sign}{amount} credits - {desc}\n"
    else:
        text += "• No transactions yet"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Referral Program", callback_data="referral")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ])
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def refer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT referral_code FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        ref_code = result[0]
        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={ref_code}"
        
        text = f"""
📊 **Referral Program**

**Your Referral Link:**
`{ref_link}`

**How it works:**
• Share your link with friends
• Each friend gets 5 bonus credits
• You earn 5 credits per referral
• No limit on referrals!

**Stats:** Use /referrals to see your referrals
"""
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text("Error generating referral code. Please contact support.")

async def referrals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    count = c.fetchone()[0]
    
    c.execute("SELECT username, first_name, join_date FROM users WHERE referred_by = ? ORDER BY join_date DESC LIMIT 10", (user_id,))
    referrals = c.fetchall()
    conn.close()
    
    text = f"📊 **Your Referrals**\n\nTotal Referrals: `{count}`\n\n"
    
    if referrals:
        text += "**Recent Referrals:**\n"
        for ref in referrals:
            username, name, date = ref
            text += f"• {name or username or 'User'} - {date[:10]}\n"
    else:
        text += "No referrals yet. Share your link!"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ==================== MAIN MENU CALLBACKS ====================
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Facebook Checker", callback_data="fb_checker"),
         InlineKeyboardButton("🔐 2FA Generator", callback_data="two_fa")],
        [InlineKeyboardButton("📧 Temp Mail", callback_data="temp_mail"),
         InlineKeyboardButton("💰 My Credits", callback_data="show_credits")],
        [InlineKeyboardButton("📊 Referral Program", callback_data="referral"),
         InlineKeyboardButton("💸 Withdraw", callback_data="withdraw_menu")],
        [InlineKeyboardButton("🆘 Support", callback_data="support"),
         InlineKeyboardButton("ℹ️ Help", callback_data="help_menu")],
    ])
    
    if is_admin(query.from_user.id):
        keyboard.inline_keyboard.append([InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")])
    
    text = f"🤖 **Main Menu**\n\nSelect an option below:\n\n💎 Credits: {get_user_credits(query.from_user.id)}"
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ==================== FACEBOOK CHECKER ====================
async def fb_checker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Check Single Number", callback_data="fb_check_single")],
        [InlineKeyboardButton("🔍 Check + Send OTP", callback_data="fb_check_otp")],
        [InlineKeyboardButton("📈 Check History", callback_data="fb_history_menu")],
        [InlineKeyboardButton("ℹ️ How it Works", callback_data="fb_info")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    credits = get_user_credits(query.from_user.id)
    
    text = f"""
📱 **Facebook Account Checker**

⚠️ **DEMO MODE - Educational Purposes Only**

**Features:**
• Check if phone number has Facebook account
• Send recovery OTP (SIMULATED)
• Check history

**Pricing:**
• Single Check: 1 credit
• Check + OTP: 2 credits

💎 **Your Credits:** {credits}

Select an option below:
"""
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def fb_check_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    credits = get_user_credits(query.from_user.id)
    
    if credits < 1:
        await query.message.edit_text("❌ **Insufficient Credits!**\n\nYou need 1 credit for this feature.\n\nUse referral program to earn free credits!", parse_mode="Markdown")
        return
    
    await query.message.edit_text("📱 **Check Single Number**\n\nSend me the phone number to check:\n\n**Format:**\n• `+8801712345678` (with country code)\n• `1234567890` (US/Canada)\n\n**Example:** `+8801712345678`\n\n⚠️ Cost: 1 credit")
    
    context.user_data['fb_check_type'] = 'single'
    return 1

async def fb_check_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    credits = get_user_credits(query.from_user.id)
    
    if credits < 2:
        await query.message.edit_text("❌ **Insufficient Credits!**\n\nYou need 2 credits for this feature.\n\nUse referral program to earn free credits!", parse_mode="Markdown")
        return
    
    await query.message.edit_text("📱 **Check + Send OTP**\n\nSend me the phone number:\n\n**What will happen:**\n1. Check if Facebook account exists\n2. If found, trigger password reset\n3. Send OTP via SMS (SIMULATED)\n\n⚠️ Cost: 2 credits\n⚠️ This is a DEMO simulation")
    
    context.user_data['fb_check_type'] = 'otp'
    return 1

async def handle_fb_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'fb_check_type' not in context.user_data:
        return
    
    check_type = context.user_data['fb_check_type']
    phone = update.message.text.strip()
    user_id = update.effective_user.id
    
    cost = 2 if check_type == 'otp' else 1
    
    # Deduct credits
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits - ? WHERE user_id = ?", (cost, user_id))
    c.execute("INSERT INTO transactions (user_id, amount, type, description, created_at) VALUES (?, ?, ?, ?, ?)",
              (user_id, -cost, 'spend', f'Facebook check - {phone[:4]}****', datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    await update.message.reply_text("🔍 **Processing...**\n\nThis may take a few seconds.", parse_mode="Markdown")
    await asyncio.sleep(2)
    
    # Perform check
    result = FacebookChecker.check_account(phone)
    
    response = f"📱 **Phone:** `{phone}`\n\n{result['message']}\n"
    
    if result['account_found']:
        response += f"\n**Account Details:**\n"
        response += f"• Name: {result['account_info']['name']}\n"
        response += f"• Created: {result['account_info']['created']}\n"
        response += f"• Last Active: {result['account_info']['last_active']}\n"
        
        if check_type == 'otp' and result['can_recover']:
            otp_result = FacebookChecker.send_recovery_otp(phone)
            if otp_result['success']:
                response += f"\n📱 **SIMULATED OTP:** `{otp_result['otp']}`\n"
                response += "⚠️ This is a simulation - No actual SMS was sent"
    
    # Log to database
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO fb_checks (user_id, phone_number, status, account_found, otp_sent, checked_at) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, phone, result['status'], 1 if result['account_found'] else 0, 1 if check_type == 'otp' else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Check Another", callback_data="fb_checker")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ])
    
    await update.message.reply_text(response, parse_mode="Markdown", reply_markup=keyboard)
    context.user_data.pop('fb_check_type', None)
    return ConversationHandler.END

async def fb_history_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT phone_number, account_found, otp_sent, checked_at FROM fb_checks WHERE user_id = ? ORDER BY checked_at DESC LIMIT 15", (user_id,))
    logs = c.fetchall()
    conn.close()
    
    if not logs:
        await query.message.edit_text("📊 **No Check History Found**\n\nUse the Facebook checker first!", parse_mode="Markdown")
        return
    
    text = "📊 **Your Facebook Check History**\n\n"
    for log in logs:
        phone, found, otp, time = log
        status = "✅ FOUND" if found else "❌ NOT FOUND"
        text += f"📱 `{phone[:4]}****{phone[-4:]}`\n"
        text += f"Status: {status}\n"
        if otp:
            text += f"OTP Sent: Yes\n"
        text += f"🕐 {time}\n"
        text += "─" * 20 + "\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Check Again", callback_data="fb_checker")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def fb_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    text = """
ℹ️ **Facebook Checker - Information**

⚠️ **IMPORTANT DISCLAIMER:**
This is a DEMO/SIMULATION tool for educational purposes only.

**How it works:**
• Checks phone number against simulated database
• Does NOT access real Facebook accounts
• Does NOT send actual SMS messages
• All OTPs shown are randomly generated

**Educational Purpose:**
This demonstrates how account checking systems work conceptually.

**For real Facebook account recovery:**
https://www.facebook.com/login/identify

**Legal Notice:**
Unauthorized access to Facebook accounts is illegal. Use responsibly.
"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="fb_checker")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ==================== 2FA MANAGER ====================
async def two_fa_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    services = TwoFAManager.get_user_services(user_id)
    
    keyboard = [
        [InlineKeyboardButton("➕ Add New Service", callback_data="two_fa_add")],
        [InlineKeyboardButton("🔄 Generate Code", callback_data="two_fa_generate")],
    ]
    
    if services:
        keyboard.append([InlineKeyboardButton("📋 My Services", callback_data="two_fa_list")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    
    text = f"""
🔐 **2FA Code Generator**

**Your Services:** {len(services)}

**Features:**
• Add multiple 2FA services
• Generate TOTP codes instantly
• Secure local storage

**How to use:**
1. Add a new service with your secret key
2. Generate codes when needed
3. Each code expires in 30 seconds

💎 **Free feature - No credits needed!**
"""
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def two_fa_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "🔐 **Add 2FA Service**\n\n"
        "Send me the details in this format:\n\n"
        "`ServiceName:SecretKey`\n\n"
        "**Example:**\n"
        "`Google:JBSWY3DPEHPK3PXP`\n\n"
        "**Where to find secret key?**\n"
        "• Google Authenticator → Export accounts\n"
        "• Microsoft Authenticator → Settings\n"
        "• Authy → Settings → Export\n\n"
        "Type /cancel to cancel."
    )
    
    context.user_data['awaiting_2fa'] = 'add'
    return 1

async def handle_two_fa_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_2fa') != 'add':
        return
    
    text = update.message.text.strip()
    
    if text == '/cancel':
        await update.message.reply_text("❌ Cancelled!")
        context.user_data.pop('awaiting_2fa', None)
        return ConversationHandler.END
    
    if ':' not in text:
        await update.message.reply_text("❌ Invalid format! Use: `ServiceName:SecretKey`", parse_mode="Markdown")
        return 1
    
    service_name, secret_key = text.split(':', 1)
    service_name = service_name.strip()
    secret_key = secret_key.strip().replace(" ", "").upper()
    
    # Validate secret
    try:
        pyotp.TOTP(secret_key).now()
    except:
        await update.message.reply_text("❌ Invalid secret key! Please check and try again.")
        return 1
    
    user_id = update.effective_user.id
    TwoFAManager.add_secret(user_id, service_name, secret_key)
    
    await update.message.reply_text(f"✅ **{service_name}** added successfully!\n\nUse /twofa to generate codes.", parse_mode="Markdown")
    context.user_data.pop('awaiting_2fa', None)
    return ConversationHandler.END

async def two_fa_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    services = TwoFAManager.get_user_services(user_id)
    
    if not services:
        await query.message.edit_text("📋 **No Services Found**\n\nAdd a service first!", parse_mode="Markdown")
        return
    
    text = "📋 **Your 2FA Services**\n\n"
    for service in services:
        service_id, name, secret, created = service
        masked_secret = secret[:6] + "*" * (len(secret) - 12) + secret[-6:] if len(secret) > 12 else "*" * len(secret)
        text += f"🔐 **{name}**\n"
        text += f"Secret: `{masked_secret}`\n"
        text += f"Added: {created[:10]}\n"
        text += "─" * 20 + "\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Generate Code", callback_data="two_fa_generate")],
        [InlineKeyboardButton("🔙 Back", callback_data="two_fa")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def two_fa_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    services = TwoFAManager.get_user_services(user_id)
    
    if not services:
        await query.message.edit_text("❌ **No Services Found**\n\nAdd a service first!", parse_mode="Markdown")
        return
    
    keyboard = []
    for service in services:
        service_id, name, secret, created = service
        keyboard.append([InlineKeyboardButton(f"🔐 {name}", callback_data=f"generate_code_{service_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="two_fa")])
    
    await query.message.edit_text("🔐 **Select a service to generate code:**", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def generate_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    service_id = int(query.data.split('_')[-1])
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT service_name, secret_key FROM totp_keys WHERE id = ? AND user_id = ?", (service_id, query.from_user.id))
    result = c.fetchone()
    conn.close()
    
    if not result:
        await query.message.edit_text("❌ Service not found!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="two_fa")]]))
        return
    
    service_name, secret_key = result
    code = TwoFAManager.generate_code(secret_key)
    
    if code:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"generate_code_{service_id}")],
            [InlineKeyboardButton("🔙 Back", callback_data="two_fa")]
        ])
        
        await query.message.edit_text(
            f"🔐 **{service_name}**\n\n"
            f"**Current Code:** `{code}`\n\n"
            f"⏱️ Code expires in 30 seconds\n"
            f"💡 Use refresh button for new code",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await query.message.edit_text("❌ Error generating code!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="two_fa")]]))

# ==================== TEMP MAIL ====================
async def temp_mail_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    emails = TempMailService.get_user_emails(user_id)
    
    keyboard = [
        [InlineKeyboardButton("📧 Create New Email", callback_data="temp_mail_create")],
    ]
    
    if emails:
        keyboard.append([InlineKeyboardButton("📥 Check Inbox", callback_data="temp_mail_inbox")])
        keyboard.append([InlineKeyboardButton("📋 My Emails", callback_data="temp_mail_list")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    
    text = f"""
📧 **Temporary Email Service**

**Active Emails:** {len(emails)}

**Features:**
• Create disposable email addresses
• Receive emails instantly
• Emails expire after 24 hours
• Completely free

💎 **Free feature - No credits needed!**
"""
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def temp_mail_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    email = TempMailService.create_temp_email(user_id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Check Inbox", callback_data="temp_mail_inbox")],
        [InlineKeyboardButton("🔙 Back", callback_data="temp_mail")]
    ])
    
    text = f"""
✅ **Temporary Email Created!**

📧 **Email:** `{email}`

**Instructions:**
• Use this email for verifications
• Check inbox for incoming messages
• Email expires in 24 hours
• Create new email anytime

💡 **Tip:** Save this email address!
"""
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def temp_mail_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    emails = TempMailService.get_user_emails(user_id)
    
    if not emails:
        await query.message.edit_text("📋 **No Emails Found**\n\nCreate an email first!", parse_mode="Markdown")
        return
    
    text = "📋 **Your Temporary Emails**\n\n"
    for email in emails:
        email_id, address, created, expires, active = email
        text += f"📧 `{address}`\n"
        text += f"Created: {created[:10]}\n"
        text += f"Expires: {expires[:10]}\n"
        text += "─" * 20 + "\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Check Inbox", callback_data="temp_mail_inbox")],
        [InlineKeyboardButton("🔙 Back", callback_data="temp_mail")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def temp_mail_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    emails = TempMailService.get_user_emails(user_id)
    
    if not emails:
        await query.message.edit_text("📭 **No Emails Found**\n\nCreate an email first!", parse_mode="Markdown")
        return
    
    # For demo, show simulated inbox
    text = "📥 **Inbox**\n\n"
    text += "📧 **Demo Mode**\n"
    text += "This is a demonstration of temp mail feature.\n\n"
    text += "**Sample emails would appear here:**\n"
    text += "• Verification code: 123456\n"
    text += "• Welcome email from service\n"
    text += "• Password reset link\n\n"
    text += "💡 In production, this would fetch real emails from the temporary email service API."
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="temp_mail_inbox")],
        [InlineKeyboardButton("📧 New Email", callback_data="temp_mail_create")],
        [InlineKeyboardButton("🔙 Back", callback_data="temp_mail")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ==================== CREDITS & WITHDRAW ====================
async def show_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    credits = get_user_credits(user_id)
    
    text = f"""
💰 **Your Balance**

💎 **Credits:** `{credits}`

**Earn More Credits:**
• Referral program: +5 per referral
• Daily bonus: +1 every day
• Special events: Follow channel

**How to use:**
• Facebook Checker: 1-2 credits
• Other features: Free

**Withdraw:** Minimum 100 credits
"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Referral Program", callback_data="referral")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw_menu")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT referral_code FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    
    if result:
        ref_code = result[0]
        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={ref_code}"
        
        text = f"""
📊 **Referral Program**

**Your Link:**
`{ref_link}`

**Stats:**
• Total Referrals: {count}
• Earnings: {count * 5} credits

**How it works:**
1. Share your unique link
2. Friend joins with your link
3. Both get 5 bonus credits
4. Unlimited referrals!

**Share link:** Copy and share with friends!
"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
        ])
        
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    credits = get_user_credits(query.from_user.id)
    
    text = f"""
💸 **Withdraw Credits**

**Your Balance:** {credits} credits

**Withdrawal Methods:**
• USDT (TRC20): Minimum 100 credits
• BTC: Minimum 200 credits
• PayPal: Minimum 50 credits

**Exchange Rate:** 10 credits = $1 USD

**To withdraw:**
Use /withdraw [amount] [method] [address]

**Example:**
`/withdraw 100 USDT TYourAddress`

⚠️ Withdrawals processed within 48 hours
"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    credits = get_user_credits(user_id)
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❌ **Invalid format!**\n\nUse: `/withdraw [amount] [method] [address]`\n\nExample: `/withdraw 100 USDT TYourAddress`", parse_mode="Markdown")
        return
    
    try:
        amount = int(args[0])
        method = args[1].upper()
        address = args[2]
        
        if amount < 50:
            await update.message.reply_text("❌ Minimum withdrawal is 50 credits!")
            return
        
        if amount > credits:
            await update.message.reply_text(f"❌ Insufficient credits! You have {credits} credits.")
            return
        
        if method not in ['USDT', 'BTC', 'PAYPAL']:
            await update.message.reply_text("❌ Invalid method! Use: USDT, BTC, or PAYPAL")
            return
        
        # Save withdrawal request
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT INTO withdraw_requests (user_id, amount, method, address, requested_at, status) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, amount, method, address, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'pending'))
        conn.commit()
        conn.close()
        
        # Deduct credits
        update_user_credits(user_id, -amount, 'withdraw', f'Withdrawal request - {amount} credits')
        
        await update.message.reply_text(f"✅ **Withdrawal Request Submitted!**\n\nAmount: {amount} credits\nMethod: {method}\nAddress: {address}\n\n⏱️ Processed within 48 hours.\n\nRequest ID: #{user_id}{amount}")
        
        # Notify admin
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, f"💰 **New Withdrawal Request**\n\nUser: {user_id}\nAmount: {amount}\nMethod: {method}\nAddress: {address}")
            except:
                pass
        
    except ValueError:
        await update.message.reply_text("❌ Invalid amount! Please enter a number.")

# ==================== SUPPORT ====================
async def support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    text = """
🆘 **Support Center**

**How can we help you?**

• **Technical Issues:** Bot not working? Contact us
• **Payment Issues:** Withdrawal problems
• **Feature Requests:** Suggest new features
• **Report Bug:** Found a bug? Let us know

**Contact Support:**
📧 Email: support@example.com
📱 Telegram: @SupportUsername

**Create Ticket:**
Use /ticket [subject] [message]

**Example:**
`/ticket Withdrawal issue My withdrawal is pending for 3 days`

Response time: 24-48 hours
"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Create Ticket", callback_data="create_ticket")],
        [InlineKeyboardButton("📋 My Tickets", callback_data="my_tickets")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def create_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "📝 **Create Support Ticket**\n\n"
        "Send me your message in this format:\n\n"
        "`Subject:Your message here`\n\n"
        "**Example:**\n"
        "`Withdrawal:My withdrawal is taking too long`\n\n"
        "Type /cancel to cancel."
    )
    
    context.user_data['awaiting_ticket'] = True
    return 1

async def handle_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_ticket'):
        return
    
    text = update.message.text.strip()
    
    if text == '/cancel':
        await update.message.reply_text("❌ Cancelled!")
        context.user_data.pop('awaiting_ticket', None)
        return ConversationHandler.END
    
    if ':' not in text:
        await update.message.reply_text("❌ Invalid format! Use: `Subject:Message`", parse_mode="Markdown")
        return 1
    
    subject, message = text.split(':', 1)
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO support_tickets (user_id, subject, message, status, created_at) VALUES (?, ?, ?, ?, ?)",
              (user_id, subject.strip(), message.strip(), 'open', datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ **Ticket Created!**\n\nTicket ID: #{user_id}\nSubject: {subject}\n\nWe'll respond within 24-48 hours.")
    
    # Notify admin
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f"📝 **New Support Ticket**\n\nUser: {user_id}\nSubject: {subject}\nMessage: {message}")
        except:
            pass
    
    context.user_data.pop('awaiting_ticket', None)
    return ConversationHandler.END

# ==================== HELP MENU ====================
async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    text = """
📖 **Help Guide**

**Commands:**
/start - Start the bot
/menu - Show main menu
/myid - Get your user ID
/credits - Check your balance
/refer - Get referral link
/referrals - View your referrals
/withdraw - Withdraw credits
/ticket - Create support ticket
/help - Show this message

**Features:**
📱 **Facebook Checker** - Check accounts (Demo)
🔐 **2FA Generator** - Generate TOTP codes
📧 **Temp Mail** - Temporary email addresses
💰 **Credit System** - Earn and use credits

**Need Help?**
• Use /ticket to create support ticket
• Contact @SupportUsername

**⚠️ Disclaimer:**
Facebook checker is DEMO only. Use responsibly.
"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ==================== ADMIN PANEL ====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 User List", callback_data="admin_users")],
        [InlineKeyboardButton("💰 Add Credits", callback_data="admin_add_credits")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📈 FB Check Logs", callback_data="admin_fb_logs")],
        [InlineKeyboardButton("💸 Withdraw Requests", callback_data="admin_withdrawals")],
        [InlineKeyboardButton("📝 Support Tickets", callback_data="admin_tickets")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await query.message.edit_text("🔧 **Admin Panel**\n\nSelect an option:", parse_mode="Markdown", reply_markup=keyboard)

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
    
    c.execute("SELECT SUM(credits) FROM users")
    total_credits = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM fb_checks")
    total_checks = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM fb_checks WHERE account_found = 1")
    accounts_found = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM totp_keys")
    totp_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM temp_emails")
    email_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'pending'")
    pending_withdrawals = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM support_tickets WHERE status = 'open'")
    open_tickets = c.fetchone()[0]
    
    conn.close()
    
    text = f"""
📊 **Bot Statistics**

👥 **Users:** {total_users}
🟢 **Active:** {active_users}
💰 **Total Credits:** {total_credits}

📱 **Facebook Checker:**
• Total Checks: {total_checks}
• Accounts Found: {accounts_found}

🔐 **Features:**
• 2FA Users: {totp_users}
• Temp Mail Users: {email_users}

📋 **Pending:**
• Withdrawals: {pending_withdrawals}
• Support Tickets: {open_tickets}

🤖 **Status:** 🟢 Online
"""
    
    await query.message.edit_text(text, parse_mode="Markdown")

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, credits, join_date FROM users ORDER BY join_date DESC LIMIT 20")
    users = c.fetchall()
    conn.close()
    
    text = "👥 **Recent Users**\n\n"
    for user in users:
        user_id, username, name, credits, date = user
        text += f"🆔 `{user_id}`\n"
        text += f"👤 {name or username or 'Unknown'}\n"
        text += f"💰 {credits} credits\n"
        text += f"📅 {date[:10]}\n"
        text += "─" * 20 + "\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def admin_add_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text("💰 **Add Credits**\n\nSend user ID and amount:\n\nFormat: `user_id amount`\n\nExample: `123456789 50`\n\nType /cancel to cancel.")
    
    context.user_data['admin_action'] = 'add_credits'
    return 1

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text("🚫 **Ban User**\n\nSend user ID to ban:\n\nFormat: `user_id`\n\nExample: `123456789`\n\nType /cancel to cancel.")
    
    context.user_data['admin_action'] = 'ban_user'
    return 1

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text("📢 **Broadcast Message**\n\nSend the message you want to broadcast to all users:\n\nType /cancel to cancel.")
    
    context.user_data['admin_action'] = 'broadcast'
    return 1

async def admin_fb_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT user_id, phone_number, account_found, otp_sent, checked_at FROM fb_checks ORDER BY checked_at DESC LIMIT 20")
    logs = c.fetchall()
    conn.close()
    
    text = "📈 **Recent Facebook Checks**\n\n"
    for log in logs:
        user_id, phone, found, otp, time = log
        text += f"👤 User: `{user_id}`\n"
        text += f"📱 Phone: {phone[:4]}****{phone[-4:]}\n"
        text += f"✅ Found: {'Yes' if found else 'No'}\n"
        text += f"📨 OTP: {'Sent' if otp else 'No'}\n"
        text += f"🕐 {time}\n"
        text += "─" * 20 + "\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def admin_withdrawals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT id, user_id, amount, method, address, status, requested_at FROM withdraw_requests WHERE status = 'pending' ORDER BY requested_at ASC")
    requests = c.fetchall()
    conn.close()
    
    if not requests:
        await query.message.edit_text("💸 **No pending withdrawal requests**", parse_mode="Markdown")
        return
    
    text = "💸 **Pending Withdrawals**\n\n"
    for req in requests:
        req_id, user_id, amount, method, address, status, time = req
        text += f"🆔 Request #{req_id}\n"
        text += f"👤 User: `{user_id}`\n"
        text += f"💰 Amount: {amount} credits\n"
        text += f"📱 Method: {method}\n"
        text += f"📍 Address: {address[:20]}...\n"
        text += f"📅 {time[:10]}\n"
        text += "─" * 20 + "\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Process", callback_data="admin_process_withdrawal")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def admin_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT id, user_id, subject, message, status, created_at FROM support_tickets WHERE status = 'open' ORDER BY created_at ASC")
    tickets = c.fetchall()
    conn.close()
    
    if not tickets:
        await query.message.edit_text("📝 **No open support tickets**", parse_mode="Markdown")
        return
    
    text = "📝 **Open Support Tickets**\n\n"
    for ticket in tickets:
        ticket_id, user_id, subject, message, status, time = ticket
        text += f"🆔 Ticket #{ticket_id}\n"
        text += f"👤 User: `{user_id}`\n"
        text += f"📋 Subject: {subject[:30]}\n"
        text += f"💬 Message: {message[:50]}...\n"
        text += f"📅 {time[:10]}\n"
        text += "─" * 20 + "\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Respond", callback_data="admin_respond_ticket")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'admin_action' not in context.user_data:
        return
    
    action = context.user_data['admin_action']
    text = update.message.text.strip()
    
    if text == '/cancel':
        await update.message.reply_text("❌ Cancelled!")
        context.user_data.pop('admin_action', None)
        return ConversationHandler.END
    
    if action == 'add_credits':
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text("❌ Invalid format! Use: `user_id amount`", parse_mode="Markdown")
            return 1
        
        try:
            user_id = int(parts[0])
            amount = int(parts[1])
            
            update_user_credits(user_id, amount, 'admin', f'Admin added {amount} credits')
            await update.message.reply_text(f"✅ Added {amount} credits to user {user_id}")
            
            # Notify user
            try:
                await context.bot.send_message(user_id, f"🎉 **{amount} credits added to your account!**\n\nThank you for using our bot!", parse_mode="Markdown")
            except:
                pass
            
        except:
            await update.message.reply_text("❌ Invalid user ID or amount!")
            return 1
    
    elif action == 'ban_user':
        try:
            user_id = int(text)
            conn = sqlite3.connect('bot_data.db')
            c = conn.cursor()
            c.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            await update.message.reply_text(f"✅ User {user_id} has been banned!")
            
            try:
                await context.bot.send_message(user_id, "🚫 **You have been banned from using this bot!**\n\nContact support for more information.", parse_mode="Markdown")
            except:
                pass
        except:
            await update.message.reply_text("❌ Invalid user ID!")
            return 1
    
    elif action == 'broadcast':
        message = text
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = c.fetchall()
        conn.close()
        
        sent = 0
        failed = 0
        
        await update.message.reply_text(f"📢 **Broadcasting to {len(users)} users...**\n\nThis may take a few minutes.", parse_mode="Markdown")
        
        for user in users:
            try:
                await context.bot.send_message(user[0], f"📢 **Announcement**\n\n{message}", parse_mode="Markdown")
                sent += 1
                await asyncio.sleep(0.05)  # Rate limit
            except:
                failed += 1
        
        # Log broadcast
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT INTO broadcasts (admin_id, message, sent_to, created_at) VALUES (?, ?, ?, ?)",
                  (update.effective_user.id, message, sent, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ **Broadcast Complete!**\n\nSent: {sent}\nFailed: {failed}")
    
    context.user_data.pop('admin_action', None)
    return ConversationHandler.END

# ==================== MAIN FUNCTION ====================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Conversation handlers
    fb_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(fb_check_single, pattern="fb_check_single"),
            CallbackQueryHandler(fb_check_otp, pattern="fb_check_otp")
        ],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fb_check)]},
        fallbacks=[]
    )
    
    twofa_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(two_fa_add, pattern="two_fa_add")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_two_fa_add)]},
        fallbacks=[]
    )
    
    ticket_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_ticket, pattern="create_ticket")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ticket)]},
        fallbacks=[]
    )
    
    admin_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_add_credits, pattern="admin_add_credits"),
            CallbackQueryHandler(admin_ban, pattern="admin_ban"),
            CallbackQueryHandler(admin_broadcast, pattern="admin_broadcast")
        ],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_action)]},
        fallbacks=[]
    )
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("credits", credits_command))
    app.add_handler(CommandHandler("refer", refer_command))
    app.add_handler(CommandHandler("referrals", referrals_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("help", help_command))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="main_menu"))
    app.add_handler(CallbackQueryHandler(fb_checker_menu, pattern="fb_checker"))
    app.add_handler(CallbackQueryHandler(fb_history_menu, pattern="fb_history_menu"))
    app.add_handler(CallbackQueryHandler(fb_info, pattern="fb_info"))
    app.add_handler(CallbackQueryHandler(two_fa_menu, pattern="two_fa"))
    app.add_handler(CallbackQueryHandler(two_fa_list, pattern="two_fa_list"))
    app.add_handler(CallbackQueryHandler(two_fa_generate, pattern="two_fa_generate"))
    app.add_handler(CallbackQueryHandler(generate_code_callback, pattern="generate_code_"))
    app.add_handler(CallbackQueryHandler(temp_mail_menu, pattern="temp_mail"))
    app.add_handler(CallbackQueryHandler(temp_mail_create, pattern="temp_mail_create"))
    app.add_handler(CallbackQueryHandler(temp_mail_list, pattern="temp_mail_list"))
    app.add_handler(CallbackQueryHandler(temp_mail_inbox, pattern="temp_mail_inbox"))
    app.add_handler(CallbackQueryHandler(show_credits, pattern="show_credits"))
    app.add_handler(CallbackQueryHandler(referral_menu, pattern="referral"))
    app.add_handler(CallbackQueryHandler(withdraw_menu, pattern="withdraw_menu"))
    app.add_handler(CallbackQueryHandler(support_menu, pattern="support"))
    app.add_handler(CallbackQueryHandler(help_menu, pattern="help_menu"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="admin_panel"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="admin_stats"))
    app.add_handler(CallbackQueryHandler(admin_users, pattern="admin_users"))
    app.add_handler(CallbackQueryHandler(admin_fb_logs, pattern="admin_fb_logs"))
    app.add_handler(CallbackQueryHandler(admin_withdrawals, pattern="admin_withdrawals"))
    app.add_handler(CallbackQueryHandler(admin_tickets, pattern="admin_tickets"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="back_to_menu"))
    
    # Conversation handlers
    app.add_handler(fb_conv_handler)
    app.add_handler(twofa_conv_handler)
    app.add_handler(ticket_conv_handler)
    app.add_handler(admin_conv_handler)
    
    print("🤖 Multi-Tool Bot is running...")
    print(f"Bot Token: {BOT_TOKEN[:15]}...")
    print(f"Admin IDs: {ADMIN_IDS}")
    print("Features: Facebook Checker, 2FA, Temp Mail, Credit System, Admin Panel")
    print("Press Ctrl+C to stop")
    
    app.run_polling()

if __name__ == "__main__":
    main()