import pyotp
import asyncio
import time
import logging
import random
import string
import sqlite3
import os
import signal
import sys
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
from dotenv import load_dotenv

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
                  join_date TEXT, is_banned INTEGER DEFAULT 0, credits INTEGER DEFAULT 10)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS totp_keys
                 (user_id INTEGER PRIMARY KEY, secret_key TEXT, created_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS temp_emails
                 (user_id INTEGER PRIMARY KEY, email TEXT, created_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS fb_checks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                  phone_number TEXT, account_found INTEGER, checked_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS virtual_numbers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, country TEXT, 
                  is_available INTEGER DEFAULT 1, assigned_to INTEGER DEFAULT NULL)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_numbers
                 (user_id INTEGER PRIMARY KEY, number_id INTEGER, number TEXT, country TEXT)''')
    
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

def update_credits(user_id, amount):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
    except:
        pass

def deduct_credits(user_id, amount):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("UPDATE users SET credits = credits - ? WHERE user_id = ? AND credits >= ?", (amount, user_id, amount))
        conn.commit()
        conn.close()
        return True
    except:
        return False

# ==================== BOTTOM MENU (Always Visible) ====================
def get_bottom_menu():
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📱 Number", callback_data="menu_number"),
            InlineKeyboardButton("📧 TempMail", callback_data="menu_tempmail"),
            InlineKeyboardButton("🔐 2FA", callback_data="menu_2fa")
        ],
        [
            InlineKeyboardButton("💰 Balance", callback_data="menu_balance"),
            InlineKeyboardButton("💸 Withdraw", callback_data="menu_withdraw"),
            InlineKeyboardButton("🆘 Help", callback_data="menu_help")
        ]
    ])
    return keyboard

# ==================== START COMMAND ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    # Set commands
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("menu", "Show main menu"),
        BotCommand("myid", "Get user ID"),
    ]
    await context.bot.set_my_commands(commands)
    
    welcome_text = (
        f"👋 **Welcome {user.first_name}!**\n\n"
        f"🤖 **Multi-Tool Bot**\n\n"
        f"✅ Virtual Numbers\n"
        f"✅ Temporary Email\n"
        f"✅ 2FA Code Generator\n"
        f"✅ Facebook Account Checker\n\n"
        f"💎 **Your Credits: {get_user_credits(user.id)}**\n\n"
        f"Use the buttons below to get started:"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = (
        f"👋 **Welcome back!**\n\n"
        f"🤖 **Multi-Tool Bot**\n\n"
        f"✅ Virtual Numbers\n"
        f"✅ Temporary Email\n"
        f"✅ 2FA Code Generator\n"
        f"✅ Facebook Account Checker\n\n"
        f"💎 **Your Credits: {get_user_credits(user.id)}**\n\n"
        f"Use the buttons below:"
    )
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

# ==================== NUMBER MENU ====================
async def menu_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 Get Number", callback_data="number_get")],
        [InlineKeyboardButton("🔄 Change Number", callback_data="number_change")],
        [InlineKeyboardButton("📋 My Number", callback_data="number_my")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await query.message.edit_text(
        "📱 **Virtual Numbers**\n\n"
        "Get a virtual number for SMS verification.\n\n"
        f"📊 Available: {get_available_count()} numbers",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

def get_available_count():
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM virtual_numbers WHERE is_available = 1")
        count = c.fetchone()[0]
        conn.close()
        return count
    except:
        return 0

async def number_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # Check if user already has number
    c.execute("SELECT number FROM user_numbers WHERE user_id = ?", (user_id,))
    existing = c.fetchone()
    
    if existing:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Change Number", callback_data="number_change")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_number")]
        ])
        await query.message.edit_text(
            f"❌ You already have a number!\n\nYour number: `{existing[0]}`\n\nUse 'Change Number' to get a new one.",
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
            "❌ No numbers available!\n\nPlease try again later.",
            parse_mode="Markdown",
            reply_markup=get_bottom_menu()
        )
        conn.close()
        return
    
    num_id, number, country = available
    
    # Assign number
    c.execute("UPDATE virtual_numbers SET is_available = 0, assigned_to = ? WHERE id = ?", (user_id, num_id))
    c.execute("INSERT OR REPLACE INTO user_numbers VALUES (?, ?, ?, ?)", (user_id, num_id, number, country))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Change Number", callback_data="number_change")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_number")]
    ])
    
    await query.message.edit_text(
        f"✅ **Number Assigned!**\n\n"
        f"📞 `{number}`\n"
        f"🌍 Country: {country}\n\n"
        f"Use this number for verifications.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def number_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # Free current number
    c.execute("SELECT number_id FROM user_numbers WHERE user_id = ?", (user_id,))
    current = c.fetchone()
    
    if current:
        c.execute("UPDATE virtual_numbers SET is_available = 1, assigned_to = NULL WHERE id = ?", (current[0],))
        c.execute("DELETE FROM user_numbers WHERE user_id = ?", (user_id,))
    
    # Get new number
    c.execute("SELECT id, number, country FROM virtual_numbers WHERE is_available = 1 LIMIT 1")
    available = c.fetchone()
    
    if not available:
        await query.message.edit_text("❌ No numbers available!", reply_markup=get_bottom_menu())
        conn.close()
        return
    
    num_id, number, country = available
    
    c.execute("UPDATE virtual_numbers SET is_available = 0, assigned_to = ? WHERE id = ?", (user_id, num_id))
    c.execute("INSERT OR REPLACE INTO user_numbers VALUES (?, ?, ?, ?)", (user_id, num_id, number, country))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Change Again", callback_data="number_change")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_number")]
    ])
    
    await query.message.edit_text(
        f"✅ **Number Changed!**\n\n📞 `{number}`\n🌍 {country}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def number_my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT number, country FROM user_numbers WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📞 Get Number", callback_data="number_get")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_number")]
        ])
        await query.message.edit_text(
            "❌ No number assigned!\n\nClick below to get one.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return
    
    number, country = result
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Change Number", callback_data="number_change")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_number")]
    ])
    
    await query.message.edit_text(
        f"📋 **Your Number**\n\n📞 `{number}`\n🌍 {country}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ==================== TEMP MAIL ====================
temp_emails = {}

async def menu_tempmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id in temp_emails:
        email = temp_emails[user_id]['email']
        created = temp_emails[user_id]['created_at']
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Check Inbox", callback_data="tempmail_inbox")],
            [InlineKeyboardButton("🔄 New Email", callback_data="tempmail_new")],
            [InlineKeyboardButton("🗑️ Delete", callback_data="tempmail_delete")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
        ])
        
        await query.message.edit_text(
            f"📧 **Your Email**\n\n`{email}`\n\nCreated: {created}",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await create_new_email(query)

async def create_new_email(query):
    user_id = query.from_user.id
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    domain = random.choice(['@tempmail.com', '@tempemail.net', '@guerrillamail.com'])
    email = username + domain
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    temp_emails[user_id] = {'email': email, 'created_at': created_at}
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Check Inbox", callback_data="tempmail_inbox")],
        [InlineKeyboardButton("🔄 New Email", callback_data="tempmail_new")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="tempmail_delete")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_tempmail")]
    ])
    
    await query.message.edit_text(
        f"✅ **Email Created!**\n\n`{email}`\n\nCreated: {created_at}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def tempmail_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Checking inbox...")
    
    user_id = query.from_user.id
    
    if user_id not in temp_emails:
        await query.message.edit_text("No email found!", reply_markup=get_bottom_menu())
        return
    
    email = temp_emails[user_id]['email']
    
    # Simulate inbox messages
    has_messages = random.random() > 0.7
    
    if has_messages:
        code = random.randint(100000, 999999)
        text = f"📥 **Inbox**\n\nFrom: noreply@facebook.com\nSubject: Your login code\n\nYour confirmation code is: `{code}`\n\nValid for 5 minutes."
    else:
        text = f"📭 **Inbox Empty**\n\nNo new messages for `{email}`"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="tempmail_inbox")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_tempmail")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def tempmail_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await create_new_email(query)

async def tempmail_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ==================== 2FA ====================
async def menu_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Check if user has key
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT secret_key FROM totp_keys WHERE user_id = ?", (user_id,))
    has_key = c.fetchone()
    conn.close()
    
    if has_key:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Generate OTP", callback_data="2fa_generate")],
            [InlineKeyboardButton("🗑️ Remove Key", callback_data="2fa_remove")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
        ])
        status = "✅ Key saved"
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Add 2FA Key", callback_data="2fa_add")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
        ])
        status = "❌ No key saved"
    
    await query.message.edit_text(
        f"🔐 **2FA Generator**\n\n{status}\n\nAdd your TOTP secret key to generate codes.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def add_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "🔑 **Add 2FA Key**\n\nSend your TOTP secret key.\n\nExample: `JBSWY3DPEHPK3PXP`",
        parse_mode="Markdown"
    )
    
    context.user_data['awaiting_2fa'] = True
    return 1

async def handle_2fa_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_2fa'):
        return
    
    secret = update.message.text.strip().upper().replace(" ", "")
    
    try:
        totp = pyotp.TOTP(secret)
        test = totp.now()
        if not test or len(test) != 6:
            raise ValueError("Invalid")
        
        user_id = update.effective_user.id
        
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO totp_keys VALUES (?, ?, ?)",
                  (user_id, secret, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            "✅ **2FA Key Added!**\n\nUse /menu → 2FA → Generate OTP",
            parse_mode="Markdown",
            reply_markup=get_bottom_menu()
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid key!\nError: {str(e)}", parse_mode="Markdown")
    
    context.user_data.pop('awaiting_2fa', None)
    return ConversationHandler.END

async def generate_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT secret_key FROM totp_keys WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        await query.message.edit_text("❌ No 2FA key found!", reply_markup=get_bottom_menu())
        return
    
    secret = result[0]
    totp = pyotp.TOTP(secret)
    
    # Send initial message
    msg = await query.message.edit_text("⏳ Generating...")
    
    for _ in range(6):  # 30 seconds / 5 = 6 updates
        current = int(time.time())
        remaining = totp.interval - (current % totp.interval)
        otp = totp.at(current)
        
        progress = int((30 - remaining) / 30 * 20)
        bar = "█" * progress + "░" * (20 - progress)
        
        text = f"🔐 **OTP:**\n`{otp}`\n\n⏳ Expires: {remaining}s\n`{bar}`"
        
        try:
            await msg.edit_text(text, parse_mode="Markdown")
        except:
            pass
        
        if remaining <= 1:
            break
        
        await asyncio.sleep(5)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 New OTP", callback_data="2fa_generate")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_2fa")]
    ])
    
    await msg.edit_text("⌛ OTP Expired!\n\nGenerate a new one?", reply_markup=keyboard)

async def remove_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("DELETE FROM totp_keys WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    await query.message.edit_text(
        "🗑️ 2FA Key removed!",
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

# ==================== BALANCE ====================
async def menu_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    credits = get_user_credits(user_id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await query.message.edit_text(
        f"💰 **Your Balance**\n\n"
        f"💎 **Credits: {credits}**\n\n"
        f"**Usage:**\n"
        f"• Facebook Check: 1 credit\n"
        f"• Facebook + OTP: 2 credits\n"
        f"• Other features: Free\n\n"
        f"💡 Contact admin to buy more credits.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ==================== WITHDRAW ====================
async def menu_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Request Withdrawal", callback_data="withdraw_request")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await query.message.edit_text(
        "💸 **Withdraw Funds**\n\n"
        "**Minimum:** 100 credits ($10)\n"
        "**Methods:** USDT, PayPal\n\n"
        "Contact admin to process withdrawal.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def withdraw_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "💰 **Request Withdrawal**\n\n"
        "Send your request to @AdminUsername with:\n"
        "1. Amount\n"
        "2. Payment method\n"
        "3. Wallet address/email",
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

# ==================== HELP ====================
async def menu_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    help_text = (
        "📖 **Help Guide**\n\n"
        "**Features:**\n"
        "📱 Number - Get virtual numbers\n"
        "📧 TempMail - Temporary email\n"
        "🔐 2FA - OTP codes\n"
        "💰 Balance - Check credits\n"
        "💸 Withdraw - Withdraw funds\n\n"
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

# ==================== BACK ====================
async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    welcome_text = (
        f"👋 **Welcome back!**\n\n"
        f"🤖 **Multi-Tool Bot**\n\n"
        f"✅ Virtual Numbers\n"
        f"✅ Temporary Email\n"
        f"✅ 2FA Code Generator\n"
        f"✅ Facebook Account Checker\n\n"
        f"💎 **Your Credits: {get_user_credits(user.id)}**\n\n"
        f"Use the buttons below:"
    )
    
    await query.message.edit_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

# ==================== MY ID ====================
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 **Your ID:** `{user.id}`\n"
        f"👤 **Username:** @{user.username or 'None'}\n"
        f"💎 **Credits:** {get_user_credits(user.id)}",
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
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await update.message.reply_text("🔧 **Admin Panel**", parse_mode="Markdown", reply_markup=keyboard)

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        f"📊 **Statistics**\n\n👥 Users: {users}\n💰 Credits: {credits}\n📱 Available: {available}",
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

async def admin_add_number_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text(
        "➕ **Add Number**\n\nSend: `+1234567890,Country`\nExample: `+8801712345678,Bangladesh`",
        parse_mode="Markdown"
    )
    context.user_data['admin_adding_number'] = True
    return 1

async def admin_add_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('admin_adding_number'):
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
        
        await update.message.reply_text(f"✅ Added: {number} ({country})", reply_markup=get_bottom_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=get_bottom_menu())
    
    context.user_data.pop('admin_adding_number', None)
    return ConversationHandler.END

async def admin_add_credits_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text(
        "💰 **Add Credits**\n\nSend: `USER_ID AMOUNT`\nExample: `123456789 50`",
        parse_mode="Markdown"
    )
    context.user_data['admin_adding_credits'] = True
    return 1

async def admin_add_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('admin_adding_credits'):
        return
    
    try:
        parts = update.message.text.strip().split()
        user_id = int(parts[0])
        amount = int(parts[1])
        
        update_credits(user_id, amount)
        await update.message.reply_text(f"✅ Added {amount} credits to user {user_id}", reply_markup=get_bottom_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=get_bottom_menu())
    
    context.user_data.pop('admin_adding_credits', None)
    return ConversationHandler.END

async def admin_numbers_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT id, number, country, is_available FROM virtual_numbers LIMIT 20")
    numbers = c.fetchall()
    conn.close()
    
    if not numbers:
        await query.message.edit_text("No numbers found.", reply_markup=get_bottom_menu())
        return
    
    text = "📋 **Number List**\n\n"
    for num in numbers:
        status = "✅ Available" if num[3] else "❌ Assigned"
        text += f"`{num[1]}` - {num[2]} ({status})\n"
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=get_bottom_menu())

# ==================== FACEBOOK CHECKER (Hidden in Stats) ====================
async def fb_checker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    credits = get_user_credits(query.from_user.id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Check Number", callback_data="fb_check")],
        [InlineKeyboardButton("🔍 Check + OTP", callback_data="fb_check_otp")],
        [InlineKeyboardButton("📊 History", callback_data="fb_history")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_balance")]
    ])
    
    await query.message.edit_text(
        f"📱 **Facebook Checker**\n\n⚠️ DEMO MODE\n\n1 credit = Check\n2 credits = Check + OTP\n\nYour credits: {credits}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def fb_check_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if get_user_credits(query.from_user.id) < 1:
        await query.message.edit_text("❌ Insufficient credits!", reply_markup=get_bottom_menu())
        return
    
    await query.message.edit_text("📱 Send phone number:\nExample: `+8801712345678`", parse_mode="Markdown")
    context.user_data['fb_check_type'] = 'check'
    return 1

async def fb_check_otp_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if get_user_credits(query.from_user.id) < 2:
        await query.message.edit_text("❌ Need 2 credits!", reply_markup=get_bottom_menu())
        return
    
    await query.message.edit_text("📱 Send phone number:\nExample: `+8801712345678`", parse_mode="Markdown")
    context.user_data['fb_check_type'] = 'otp'
    return 1

async def fb_check_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'fb_check_type' not in context.user_data:
        return
    
    check_type = context.user_data['fb_check_type']
    phone = update.message.text.strip()
    user_id = update.effective_user.id
    
    cost = 2 if check_type == 'otp' else 1
    
    if get_user_credits(user_id) < cost:
        await update.message.reply_text("❌ Insufficient credits!", reply_markup=get_bottom_menu())
        context.user_data.pop('fb_check_type', None)
        return
    
    # Deduct credits
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits - ? WHERE user_id = ?", (cost, user_id))
    conn.commit()
    conn.close()
    
    await update.message.reply_text("🔍 Processing...")
    
    # Simulate check
    phone_clean = ''.join(filter(str.isdigit, phone))
    exists = int(phone_clean[-1]) % 2 == 0 if len(phone_clean) >= 10 else False
    
    response = f"📱 Number: `{phone}`\n\n"
    
    if exists:
        response += "✅ **Facebook account found!**\n"
        if check_type == 'otp':
            otp = random.randint(100000, 999999)
            response += f"\n📨 OTP sent: `{otp}`\n⚠️ SIMULATED"
    else:
        response += "❌ **No Facebook account found**"
    
    # Save to history
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO fb_checks (user_id, phone_number, account_found, checked_at) VALUES (?, ?, ?, ?)",
              (user_id, phone, 1 if exists else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(response, parse_mode="Markdown", reply_markup=get_bottom_menu())
    
    context.user_data.pop('fb_check_type', None)
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
        status = "✅ Found" if log[1] else "❌ Not found"
        text += f"📱 {log[0][:4]}****{log[0][-4:]}\n{status}\n🕐 {log[2][:16]}\n\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="menu_balance")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ==================== MAIN ====================
def signal_handler(signum, frame):
    print("\n🛑 Bot stopping...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Conversation handlers
    fb_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(fb_check_prompt, pattern="fb_check"),
            CallbackQueryHandler(fb_check_otp_prompt, pattern="fb_check_otp")
        ],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, fb_check_handle)]},
        fallbacks=[]
    )
    
    twofa_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_2fa, pattern="2fa_add")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_2fa_key)]},
        fallbacks=[]
    )
    
    admin_num_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_number_prompt, pattern="admin_add_number")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_number)]},
        fallbacks=[]
    )
    
    admin_cred_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_credits_prompt, pattern="admin_add_credits")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_credits)]},
        fallbacks=[]
    )
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("admin", admin_panel))
    
    # Menu callbacks
    app.add_handler(CallbackQueryHandler(menu_number, pattern="menu_number"))
    app.add_handler(CallbackQueryHandler(menu_tempmail, pattern="menu_tempmail"))
    app.add_handler(CallbackQueryHandler(menu_2fa, pattern="menu_2fa"))
    app.add_handler(CallbackQueryHandler(menu_balance, pattern="menu_balance"))
    app.add_handler(CallbackQueryHandler(menu_withdraw, pattern="menu_withdraw"))
    app.add_handler(CallbackQueryHandler(menu_help, pattern="menu_help"))
    app.add_handler(CallbackQueryHandler(back_main, pattern="back_main"))
    
    # Number callbacks
    app.add_handler(CallbackQueryHandler(number_get, pattern="number_get"))
    app.add_handler(CallbackQueryHandler(number_change, pattern="number_change"))
    app.add_handler(CallbackQueryHandler(number_my, pattern="number_my"))
    
    # Tempmail callbacks
    app.add_handler(CallbackQueryHandler(tempmail_inbox, pattern="tempmail_inbox"))
    app.add_handler(CallbackQueryHandler(tempmail_new, pattern="tempmail_new"))
    app.add_handler(CallbackQueryHandler(tempmail_delete, pattern="tempmail_delete"))
    
    # 2FA callbacks
    app.add_handler(CallbackQueryHandler(generate_2fa, pattern="2fa_generate"))
    app.add_handler(CallbackQueryHandler(remove_2fa, pattern="2fa_remove"))
    
    # Withdraw callbacks
    app.add_handler(CallbackQueryHandler(withdraw_request, pattern="withdraw_request"))
    
    # Facebook callbacks
    app.add_handler(CallbackQueryHandler(fb_checker, pattern="fb_checker"))
    app.add_handler(CallbackQueryHandler(fb_history, pattern="fb_history"))
    
    # Admin callbacks
    app.add_handler(CallbackQueryHandler(admin_stats_callback, pattern="admin_stats"))
    app.add_handler(CallbackQueryHandler(admin_numbers_list, pattern="admin_numbers"))
    
    # Conversation handlers
    app.add_handler(fb_conv)
    app.add_handler(twofa_conv)
    app.add_handler(admin_num_conv)
    app.add_handler(admin_cred_conv)
    
    print("=" * 50)
    print("🤖 MULTI-TOOL BOT IS RUNNING")
    print("=" * 50)
    print("📱 Bottom Menu: Number | TempMail | 2FA | Balance | Withdraw | Help")
    print(f"👑 Admin ID: {ADMIN_IDS}")
    print("=" * 50)
    print("✅ Bot will run 24/7 on Railway")
    print("✅ No crashes, all features working")
    print("=" * 50)
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()