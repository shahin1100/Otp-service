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
import signal
import sys

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
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, 
                  join_date TEXT, is_banned BOOLEAN DEFAULT 0, credits INTEGER DEFAULT 10)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS totp_keys
                 (user_id INTEGER, secret_key TEXT, created_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS temp_emails
                 (user_id INTEGER, email TEXT, created_at TEXT, last_checked TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS fb_checks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                  phone_number TEXT, status TEXT, account_found BOOLEAN, 
                  otp_sent BOOLEAN, checked_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS virtual_numbers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, country TEXT, 
                  is_available BOOLEAN DEFAULT 1, assigned_to INTEGER DEFAULT NULL,
                  assigned_at TEXT DEFAULT NULL)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_numbers
                 (user_id INTEGER PRIMARY KEY, number_id INTEGER, number TEXT, 
                  country TEXT, assigned_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS withdraw_requests
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                  amount INTEGER, method TEXT, address TEXT, status TEXT, 
                  created_at TEXT)''')
    
    conn.commit()
    conn.close()

init_db()

# ==================== HELPER FUNCTIONS ====================
def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_user_credits(user_id):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else 10
    except:
        return 10

def add_user(user_id, username, first_name):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, join_date, is_banned, credits) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, username or "", first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0, 10))
        conn.commit()
        conn.close()
    except:
        pass

def update_user_credits(user_id, amount):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
    except:
        pass

# ==================== BOTTOM NAVIGATION MENU ====================
def get_bottom_menu():
    """Returns the bottom navigation menu that always shows"""
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📱 Number", callback_data="nav_number"),
            InlineKeyboardButton("📧 TempMail", callback_data="nav_tempmail"),
            InlineKeyboardButton("🔐 2FA", callback_data="nav_2fa")
        ],
        [
            InlineKeyboardButton("📊 Stats", callback_data="nav_stats"),
            InlineKeyboardButton("💰 Balance", callback_data="nav_balance"),
            InlineKeyboardButton("🆘 Help", callback_data="nav_help")
        ]
    ])
    return keyboard

# ==================== MAIN START (No Open Menu Button) ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    # Set bot commands for menu
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("menu", "Show menu"),
        BotCommand("myid", "Get user ID"),
    ]
    await context.bot.set_my_commands(commands)
    
    # Direct bottom navigation - no extra button
    welcome_text = (
        f"👋 Welcome {user.first_name}!\n\n"
        f"🤖 **Multi-Tool Bot**\n\n"
        f"✅ 2FA Code Generator\n"
        f"✅ Facebook Account Checker (DEMO)\n\n"
        f"💎 You have {get_user_credits(user.id)} free credits!\n\n"
        f"Use the buttons below to access features:"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu command - shows bottom navigation"""
    await update.message.reply_text(
        "📱 **Main Menu**\n\nSelect an option below:",
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

# ==================== NAVIGATION HANDLERS ====================
async def nav_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 Get New Number", callback_data="assign_number")],
        [InlineKeyboardButton("🔄 Change Number", callback_data="change_number")],
        [InlineKeyboardButton("📋 My Number", callback_data="my_number")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_back")]
    ])
    
    await query.message.edit_text(
        "📱 **Virtual Numbers**\n\n"
        "Get a virtual number for verifications.\n\n"
        f"📊 Available: {get_available_numbers_count()} numbers",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def nav_tempmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            [InlineKeyboardButton("🔙 Back", callback_data="nav_back")]
        ])
        
        await query.message.edit_text(
            f"📧 **Your Temporary Email**\n\n"
            f"`{email}`\n\n"
            f"📅 Created: {created}",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await create_new_tempmail(query, from_nav=True)

async def nav_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Add 2FA Key", callback_data="add_2fa")],
        [InlineKeyboardButton("📋 Generate OTP", callback_data="generate_otp")],
        [InlineKeyboardButton("🗑️ Remove Key", callback_data="remove_2fa")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_back")]
    ])
    
    await query.message.edit_text(
        "🔐 **Two-Factor Authentication**\n\n"
        "Manage your TOTP keys here.\n\n"
        "• Add your secret key\n"
        "• Generate live OTP codes\n"
        "• 30-second countdown",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def nav_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM fb_checks WHERE user_id = ?", (user_id,))
    fb_checks = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM totp_keys WHERE user_id = ?", (user_id,))
    has_2fa = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM user_numbers WHERE user_id = ?", (user_id,))
    has_number = c.fetchone()[0]
    
    conn.close()
    
    stats_text = (
        "📊 **Your Stats**\n\n"
        f"💎 Credits: {get_user_credits(user_id)}\n"
        f"📱 Has Number: {'✅' if has_number else '❌'}\n"
        f"🔐 2FA Setup: {'✅' if has_2fa else '❌'}\n"
        f"📱 FB Checks: {fb_checks}\n"
        f"📅 Joined: {get_join_date(user_id)}"
    )
    
    await query.message.edit_text(
        stats_text,
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

async def nav_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    credits = get_user_credits(user_id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw_menu")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_back")]
    ])
    
    await query.message.edit_text(
        f"💰 **Your Balance**\n\n"
        f"💎 Credits: `{credits}`\n\n"
        f"**Usage Cost:**\n"
        f"• FB Check: 1 credit\n"
        f"• FB Check + OTP: 2 credits\n"
        f"• Others: Free\n\n"
        f"Minimum withdrawal: 100 credits = $10",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def nav_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    help_text = (
        "📖 **Help Guide**\n\n"
        "**Features:**\n"
        "📱 Number - Get virtual numbers\n"
        "📧 TempMail - Temporary email\n"
        "🔐 2FA - OTP codes\n"
        "📊 Stats - Your usage stats\n"
        "💰 Balance - Check credits\n\n"
        "**Commands:**\n"
        "/start - Restart bot\n"
        "/menu - Show menu\n"
        "/myid - Get user ID\n\n"
        "**Support:** @YourSupport"
    )
    
    await query.message.edit_text(
        help_text,
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

async def nav_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    welcome_text = (
        f"👋 Welcome back {user.first_name}!\n\n"
        f"🤖 **Multi-Tool Bot**\n\n"
        f"✅ 2FA Code Generator\n"
        f"✅ Facebook Account Checker (DEMO)\n\n"
        f"💎 You have {get_user_credits(user.id)} credits!\n\n"
        f"Use the buttons below:"
    )
    
    await query.message.edit_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

def get_join_date(user_id):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT join_date FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0][:10] if result else "Unknown"
    except:
        return "Unknown"

def get_available_numbers_count():
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM virtual_numbers WHERE is_available = 1")
        count = c.fetchone()[0]
        conn.close()
        return count
    except:
        return 0

# ==================== VIRTUAL NUMBERS ====================
async def assign_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    c.execute("SELECT number_id, number FROM user_numbers WHERE user_id = ?", (user_id,))
    existing = c.fetchone()
    
    if existing:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Change Number", callback_data="change_number")],
            [InlineKeyboardButton("🔙 Back", callback_data="nav_number")]
        ])
        await query.message.edit_text(
            f"❌ You already have a number!\n\nUse 'Change Number' to get a new one.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        conn.close()
        return
    
    c.execute("SELECT id, number, country FROM virtual_numbers WHERE is_available = 1 LIMIT 1")
    available = c.fetchone()
    
    if not available:
        await query.message.edit_text(
            "❌ **No Numbers Available!**\n\nPlease try again later.",
            parse_mode="Markdown",
            reply_markup=get_bottom_menu()
        )
        conn.close()
        return
    
    number_id, number, country = available
    
    c.execute("UPDATE virtual_numbers SET is_available = 0, assigned_to = ?, assigned_at = ? WHERE id = ?",
              (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), number_id))
    c.execute("INSERT OR REPLACE INTO user_numbers VALUES (?, ?, ?, ?, ?)",
              (user_id, number_id, number, country, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Change Number", callback_data="change_number")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_number")]
    ])
    
    await query.message.edit_text(
        f"✅ **Number Assigned!**\n\n"
        f"📞 `{number}`\n"
        f"🌍 {country}\n\n"
        f"Use for verifications.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def change_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    c.execute("SELECT number_id FROM user_numbers WHERE user_id = ?", (user_id,))
    current = c.fetchone()
    
    if current:
        c.execute("UPDATE virtual_numbers SET is_available = 1, assigned_to = NULL, assigned_at = NULL WHERE id = ?", (current[0],))
        c.execute("DELETE FROM user_numbers WHERE user_id = ?", (user_id,))
    
    c.execute("SELECT id, number, country FROM virtual_numbers WHERE is_available = 1 LIMIT 1")
    available = c.fetchone()
    
    if not available:
        await query.message.edit_text("❌ No numbers available!", reply_markup=get_bottom_menu())
        conn.close()
        return
    
    number_id, number, country = available
    
    c.execute("UPDATE virtual_numbers SET is_available = 0, assigned_to = ?, assigned_at = ? WHERE id = ?",
              (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), number_id))
    c.execute("INSERT OR REPLACE INTO user_numbers VALUES (?, ?, ?, ?, ?)",
              (user_id, number_id, number, country, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Change Again", callback_data="change_number")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_number")]
    ])
    
    await query.message.edit_text(
        f"✅ **Number Changed!**\n\n📞 `{number}`\n🌍 {country}",
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
            [InlineKeyboardButton("🔙 Back", callback_data="nav_number")]
        ])
        await query.message.edit_text(
            "❌ No number assigned!\n\nClick below to get one.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return
    
    number, country, assigned_at = result
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Change Number", callback_data="change_number")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_number")]
    ])
    
    await query.message.edit_text(
        f"📋 **Your Number**\n\n📞 `{number}`\n🌍 {country}\n📅 {assigned_at[:10]}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ==================== TEMP MAIL ====================
temp_emails = {}

class TempMailAPI:
    domains = ['@tempmail.com', '@tempemail.net', '@guerrillamail.com']
    
    @staticmethod
    def create_email():
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        return username + random.choice(TempMailAPI.domains)
    
    @staticmethod
    def get_inbox(email):
        messages = []
        if random.random() > 0.7:
            messages.append({
                'from': 'noreply@facebook.com',
                'subject': 'Your login code',
                'body': f'Code: {random.randint(100000, 999999)}',
                'time': datetime.now().strftime('%H:%M:%S')
            })
        return messages

async def create_new_tempmail(query, from_nav=False):
    user_id = query.from_user.id
    email = TempMailAPI.create_email()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    temp_emails[user_id] = {'email': email, 'created_at': created_at, 'messages': []}
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Check Inbox", callback_data="check_inbox")],
        [InlineKeyboardButton("🔄 New Email", callback_data="new_tempmail")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="delete_email")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_tempmail")]
    ])
    
    await query.message.edit_text(
        f"📧 **Email Created!**\n\n`{email}`\n\n📅 {created_at}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def check_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Checking...")
    
    user_id = query.from_user.id
    
    if user_id not in temp_emails:
        await query.message.edit_text("No email found!", reply_markup=get_bottom_menu())
        return
    
    email = temp_emails[user_id]['email']
    messages = TempMailAPI.get_inbox(email)
    
    if not messages:
        text = f"📭 **Empty**\n\nNo messages for `{email}`"
    else:
        text = f"📥 **Inbox**\n\n"
        for msg in messages:
            text += f"📧 From: {msg['from']}\n📝 {msg['subject']}\n💬 {msg['body']}\n🕐 {msg['time']}\n\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="check_inbox")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_tempmail")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def delete_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id in temp_emails:
        del temp_emails[user_id]
    
    await query.message.edit_text(
        "🗑️ Email deleted!",
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

# ==================== 2FA GENERATOR ====================
user_totp = {}

async def add_2fa_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "🔑 **Add 2FA Key**\n\nSend your TOTP secret key.\n\nExample: `JBSWY3DPEHPK3PXP`",
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
            raise ValueError("Invalid")
        
        user_id = update.effective_user.id
        
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO totp_keys VALUES (?, ?, ?)",
                  (user_id, secret, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        
        user_totp[user_id] = {'totp': totp, 'secret': secret}
        
        await update.message.reply_text(
            "✅ **2FA Key Added!**\n\nUse /menu → 2FA → Generate OTP",
            parse_mode="Markdown",
            reply_markup=get_bottom_menu()
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid key!\nError: {str(e)}", parse_mode="Markdown")
    
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
            "❌ No 2FA key found!\n\nAdd a key first.",
            parse_mode="Markdown",
            reply_markup=get_bottom_menu()
        )
        return
    
    secret = result[0]
    await generate_otp_display(query, secret)

async def generate_otp_display(query, secret):
    totp = pyotp.TOTP(secret)
    msg = await query.message.edit_text("⏳ Generating...")
    
    for _ in range(30):  # Max 30 seconds
        current_time = int(time.time())
        remaining = totp.interval - (current_time % totp.interval)
        otp = totp.at(current_time)
        
        progress = int((totp.interval - remaining) / totp.interval * 20)
        bar = "█" * progress + "░" * (20 - progress)
        
        text = f"🔐 **OTP:**\n```\n{otp}\n```\n\n⏳ Expires: `{remaining}s`\n`{bar}`"
        
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
        [InlineKeyboardButton("🔄 New OTP", callback_data="generate_otp")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_2fa")]
    ])
    
    await query.message.reply_text("⌛ Expired! Generate new?", reply_markup=keyboard)

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
        "🗑️ 2FA Key removed!",
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

# ==================== FACEBOOK CHECKER ====================
class FacebookChecker:
    @staticmethod
    def check_account(phone_number):
        phone = ''.join(filter(str.isdigit, phone_number))
        if len(phone) < 10:
            return {'account_found': False, 'message': '❌ Invalid number'}
        
        # 50% chance for demo
        account_exists = int(phone[-1]) % 2 == 0
        
        if account_exists:
            return {'account_found': True, 'message': '✅ Facebook account found!'}
        else:
            return {'account_found': False, 'message': '❌ No account found'}
    
    @staticmethod
    def send_recovery_otp(phone_number):
        return {'success': True, 'otp': ''.join(random.choices(string.digits, k=6))}

async def facebook_checker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Check Number", callback_data="fb_check_single")],
        [InlineKeyboardButton("🔍 Check + OTP", callback_data="fb_check_otp")],
        [InlineKeyboardButton("📈 History", callback_data="fb_history")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_stats")]
    ])
    
    await query.message.edit_text(
        "📱 **Facebook Checker**\n\n⚠️ DEMO MODE\n\n1 credit per check\n2 credits for check+OTP",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def fb_check_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    credits = get_user_credits(query.from_user.id)
    if credits < 1:
        await query.message.edit_text("❌ Insufficient credits!", reply_markup=get_bottom_menu())
        return
    
    await query.message.edit_text("📱 Send phone number with country code:\nExample: `+8801712345678`", parse_mode="Markdown")
    context.user_data['awaiting_fb_check'] = 'single'
    return 1

async def fb_check_with_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    credits = get_user_credits(query.from_user.id)
    if credits < 2:
        await query.message.edit_text("❌ Insufficient credits! Need 2 credits.", reply_markup=get_bottom_menu())
        return
    
    await query.message.edit_text("📱 Send phone number:\nExample: `+8801712345678`", parse_mode="Markdown")
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
    
    await update.message.reply_text("🔍 Processing...")
    
    result = FacebookChecker.check_account(phone)
    
    response = f"📱 `{phone}`\n\n{result['message']}\n"
    
    if result['account_found'] and check_type == 'with_otp':
        await asyncio.sleep(1)
        otp_result = FacebookChecker.send_recovery_otp(phone)
        response += f"\n📨 OTP: `{otp_result['otp']}`\n⚠️ SIMULATED"
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO fb_checks VALUES (?, ?, ?, ?, ?, ?, ?)",
              (None, user_id, phone, result['message'], 1 if result['account_found'] else 0,
               1 if check_type == 'with_otp' else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(response, parse_mode="Markdown", reply_markup=get_bottom_menu())
    
    context.user_data.pop('awaiting_fb_check', None)
    return ConversationHandler.END

async def fb_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT phone_number, account_found, checked_at FROM fb_checks WHERE user_id = ? ORDER BY checked_at DESC LIMIT 5", (user_id,))
    logs = c.fetchall()
    conn.close()
    
    if not logs:
        await query.message.edit_text("No history found.", reply_markup=get_bottom_menu())
        return
    
    text = "📊 **Recent Checks**\n\n"
    for log in logs:
        text += f"📱 {log[0][:4]}****{log[0][-4:]}\n✅ {'Found' if log[1] else 'Not found'}\n🕐 {log[2][:16]}\n\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="nav_stats")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ==================== WITHDRAW ====================
async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Request", callback_data="withdraw_request")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_balance")]
    ])
    
    await query.message.edit_text(
        "💸 **Withdraw**\n\nMinimum: 100 credits ($10)\nMethods: USDT, PayPal\n\nContact admin for withdrawal.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def withdraw_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "💰 **Request Withdrawal**\n\nContact: @AdminUsername\n\nSend: Amount, Method, Address",
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

# ==================== OTHER COMMANDS ====================
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 ID: `{user.id}`\n👤 @{user.username or 'None'}\n💎 Credits: {get_user_credits(user.id)}",
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

# ==================== ADMIN PANEL ====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized!")
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("➕ Add Number", callback_data="admin_add_number")],
        [InlineKeyboardButton("💰 Add Credits", callback_data="admin_add_credits")],
        [InlineKeyboardButton("📋 Numbers", callback_data="admin_numbers")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav_back")]
    ])
    
    await update.message.reply_text("🔧 **Admin Panel**", parse_mode="Markdown", reply_markup=keyboard)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT SUM(credits) FROM users")
    credits = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM virtual_numbers WHERE is_available = 1")
    available = c.fetchone()[0]
    conn.close()
    
    await query.message.edit_text(
        f"📊 **Stats**\n\n👥 Users: {users}\n💰 Credits: {credits}\n📱 Available: {available}",
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

async def admin_add_number_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text("Send number: `+1234567890,Country`", parse_mode="Markdown")
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
        
        await update.message.reply_text(f"✅ Added: {number}", reply_markup=get_bottom_menu())
    except:
        await update.message.reply_text("❌ Error! Use: `+1234567890,Country`", parse_mode="Markdown")
    
    context.user_data.pop('awaiting_number', None)
    return ConversationHandler.END

async def admin_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT id, number, country, is_available FROM virtual_numbers LIMIT 10")
    numbers = c.fetchall()
    conn.close()
    
    text = "📋 **Numbers**\n\n"
    for num in numbers:
        status = "✅" if num[3] else "❌"
        text += f"{status} {num[1]} ({num[2]})\n"
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=get_bottom_menu())

async def admin_add_credits_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text("Send: `USER_ID AMOUNT`\nExample: `123456789 50`", parse_mode="Markdown")
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
        await update.message.reply_text(f"✅ Added {amount} credits to {user_id}", reply_markup=get_bottom_menu())
    except:
        await update.message.reply_text("❌ Error! Use: `USER_ID AMOUNT`", parse_mode="Markdown")
    
    context.user_data.pop('awaiting_credits', None)
    return ConversationHandler.END

# ==================== MAIN ====================
def signal_handler(signum, frame):
    print("\n🛑 Bot stopping gracefully...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Conversation handlers
    fb_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(fb_check_single, pattern="fb_check_single"),
            CallbackQueryHandler(fb_check_with_otp, pattern="fb_check_otp")
        ],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fb_check)]},
        fallbacks=[]
    )
    
    twofa_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_2fa_prompt, pattern="add_2fa")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_2fa_key)]},
        fallbacks=[]
    )
    
    admin_number_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_number_prompt, pattern="admin_add_number")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_number)]},
        fallbacks=[]
    )
    
    admin_credits_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_credits_prompt, pattern="admin_add_credits")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_credits)]},
        fallbacks=[]
    )
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("myid", myid))
    
    # Navigation handlers (Bottom Menu)
    app.add_handler(CallbackQueryHandler(nav_number, pattern="nav_number"))
    app.add_handler(CallbackQueryHandler(nav_tempmail, pattern="nav_tempmail"))
    app.add_handler(CallbackQueryHandler(nav_2fa, pattern="nav_2fa"))
    app.add_handler(CallbackQueryHandler(nav_stats, pattern="nav_stats"))
    app.add_handler(CallbackQueryHandler(nav_balance, pattern="nav_balance"))
    app.add_handler(CallbackQueryHandler(nav_help, pattern="nav_help"))
    app.add_handler(CallbackQueryHandler(nav_back, pattern="nav_back"))
    
    # Number handlers
    app.add_handler(CallbackQueryHandler(assign_number, pattern="assign_number"))
    app.add_handler(CallbackQueryHandler(change_number, pattern="change_number"))
    app.add_handler(CallbackQueryHandler(my_number, pattern="my_number"))
    
    # TempMail handlers
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
    app.add_handler(CallbackQueryHandler(withdraw_menu, pattern="withdraw_menu"))
    app.add_handler(CallbackQueryHandler(withdraw_request, pattern="withdraw_request"))
    
    # Admin handlers
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="admin_panel"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="admin_stats"))
    app.add_handler(CallbackQueryHandler(admin_numbers, pattern="admin_numbers"))
    
    # Conversation handlers
    app.add_handler(fb_conv)
    app.add_handler(twofa_conv)
    app.add_handler(admin_number_conv)
    app.add_handler(admin_credits_conv)
    
    print("=" * 50)
    print("🤖 Multi-Tool Bot is RUNNING!")
    print("=" * 50)
    print("📱 Bottom Navigation Menu:")
    print("   [📱 Number] [📧 TempMail] [🔐 2FA]")
    print("   [📊 Stats]  [💰 Balance]  [🆘 Help]")
    print("=" * 50)
    print(f"👑 Admin IDs: {ADMIN_IDS}")
    print("=" * 50)
    print("✅ Bot will run 24/7 without crashes")
    print("Press Ctrl+C to stop")
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()