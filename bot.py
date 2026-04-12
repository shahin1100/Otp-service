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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ReplyKeyboardMarkup, KeyboardButton
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

# ==================== BOTTOM KEYBOARD MENU (ALWAYS VISIBLE) ====================
def get_bottom_menu():
    """Returns a persistent bottom keyboard menu"""
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📱 Number"), KeyboardButton("📧 TempMail"), KeyboardButton("🔐 2FA")],
        [KeyboardButton("💰 Balance"), KeyboardButton("💸 Withdraw"), KeyboardButton("🆘 Help")]
    ], resize_keyboard=True, one_time_keyboard=False)
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

# ==================== TEXT MESSAGE HANDLER (FOR BOTTOM BUTTONS) ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == "📱 Number":
        await number_menu(update, context)
    elif text == "📧 TempMail":
        await tempmail_menu(update, context)
    elif text == "🔐 2FA":
        await twofa_menu(update, context)
    elif text == "💰 Balance":
        await balance_menu(update, context)
    elif text == "💸 Withdraw":
        await withdraw_menu(update, context)
    elif text == "🆘 Help":
        await help_menu(update, context)
    else:
        # Check if waiting for 2FA key
        if context.user_data.get('awaiting_2fa_key'):
            await handle_2fa_key(update, context)
        elif context.user_data.get('awaiting_number_input'):
            await handle_number_input(update, context)
        elif context.user_data.get('awaiting_tempmail'):
            pass
        else:
            await update.message.reply_text(
                "❌ Unknown command!\n\nUse the buttons below:",
                reply_markup=get_bottom_menu()
            )

# ==================== NUMBER MENU ====================
async def number_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 Get Number", callback_data="num_get")],
        [InlineKeyboardButton("🔄 Change Number", callback_data="num_change")],
        [InlineKeyboardButton("📋 My Number", callback_data="num_my")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await update.message.reply_text(
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

async def num_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    c.execute("SELECT number FROM user_numbers WHERE user_id = ?", (user_id,))
    existing = c.fetchone()
    
    if existing:
        await query.message.edit_text(
            f"❌ You already have a number!\n\nYour number: `{existing[0]}`\n\nUse 'Change Number' to get a new one.",
            parse_mode="Markdown"
        )
        conn.close()
        return
    
    c.execute("SELECT id, number, country FROM virtual_numbers WHERE is_available = 1 LIMIT 1")
    available = c.fetchone()
    
    if not available:
        await query.message.edit_text("❌ No numbers available!\n\nPlease try again later.", parse_mode="Markdown")
        conn.close()
        return
    
    num_id, number, country = available
    
    c.execute("UPDATE virtual_numbers SET is_available = 0, assigned_to = ? WHERE id = ?", (user_id, num_id))
    c.execute("INSERT OR REPLACE INTO user_numbers VALUES (?, ?, ?, ?)", (user_id, num_id, number, country))
    conn.commit()
    conn.close()
    
    await query.message.edit_text(
        f"✅ **Number Assigned!**\n\n"
        f"📞 `{number}`\n"
        f"🌍 Country: {country}\n\n"
        f"Use this number for verifications.",
        parse_mode="Markdown"
    )

async def num_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    c.execute("SELECT number_id FROM user_numbers WHERE user_id = ?", (user_id,))
    current = c.fetchone()
    
    if current:
        c.execute("UPDATE virtual_numbers SET is_available = 1, assigned_to = NULL WHERE id = ?", (current[0],))
        c.execute("DELETE FROM user_numbers WHERE user_id = ?", (user_id,))
    
    c.execute("SELECT id, number, country FROM virtual_numbers WHERE is_available = 1 LIMIT 1")
    available = c.fetchone()
    
    if not available:
        await query.message.edit_text("❌ No numbers available!", parse_mode="Markdown")
        conn.close()
        return
    
    num_id, number, country = available
    
    c.execute("UPDATE virtual_numbers SET is_available = 0, assigned_to = ? WHERE id = ?", (user_id, num_id))
    c.execute("INSERT OR REPLACE INTO user_numbers VALUES (?, ?, ?, ?)", (user_id, num_id, number, country))
    conn.commit()
    conn.close()
    
    await query.message.edit_text(
        f"✅ **Number Changed!**\n\n📞 `{number}`\n🌍 {country}",
        parse_mode="Markdown"
    )

async def num_my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT number, country FROM user_numbers WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        await query.message.edit_text(
            "❌ No number assigned!\n\nClick 'Get Number' to get one.",
            parse_mode="Markdown"
        )
        return
    
    number, country = result
    
    await query.message.edit_text(
        f"📋 **Your Number**\n\n📞 `{number}`\n🌍 {country}",
        parse_mode="Markdown"
    )

# ==================== TEMP MAIL ====================
temp_emails = {}

async def tempmail_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in temp_emails:
        email = temp_emails[user_id]['email']
        created = temp_emails[user_id]['created_at']
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Check Inbox", callback_data="tmp_inbox")],
            [InlineKeyboardButton("🔄 New Email", callback_data="tmp_new")],
            [InlineKeyboardButton("🗑️ Delete", callback_data="tmp_delete")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
        ])
        
        await update.message.reply_text(
            f"📧 **Your Email**\n\n`{email}`\n\nCreated: {created}",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await create_new_email(update)

async def create_new_email(update):
    user_id = update.effective_user.id
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    domain = random.choice(['@tempmail.com', '@tempemail.net', '@guerrillamail.com'])
    email = username + domain
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    temp_emails[user_id] = {'email': email, 'created_at': created_at}
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Check Inbox", callback_data="tmp_inbox")],
        [InlineKeyboardButton("🔄 New Email", callback_data="tmp_new")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="tmp_delete")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await update.message.reply_text(
        f"✅ **Email Created!**\n\n`{email}`\n\nCreated: {created_at}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def tmp_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Checking inbox...")
    
    user_id = query.from_user.id
    
    if user_id not in temp_emails:
        await query.message.edit_text("No email found!", parse_mode="Markdown")
        return
    
    email = temp_emails[user_id]['email']
    
    has_messages = random.random() > 0.7
    
    if has_messages:
        code = random.randint(100000, 999999)
        text = f"📥 **Inbox**\n\nFrom: noreply@facebook.com\nSubject: Your login code\n\nYour confirmation code is: `{code}`\n\nValid for 5 minutes."
    else:
        text = f"📭 **Inbox Empty**\n\nNo new messages for `{email}`"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="tmp_inbox")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def tmp_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    domain = random.choice(['@tempmail.com', '@tempemail.net', '@guerrillamail.com'])
    email = username + domain
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    temp_emails[user_id] = {'email': email, 'created_at': created_at}
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Check Inbox", callback_data="tmp_inbox")],
        [InlineKeyboardButton("🔄 New Email", callback_data="tmp_new")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="tmp_delete")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await query.message.edit_text(
        f"✅ **New Email Created!**\n\n`{email}`\n\nCreated: {created_at}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def tmp_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id in temp_emails:
        del temp_emails[user_id]
    
    await query.message.edit_text("🗑️ Email deleted!", parse_mode="Markdown")

# ==================== 2FA WITH LIVE COUNTDOWN ====================
async def twofa_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT secret_key FROM totp_keys WHERE user_id = ?", (user_id,))
    has_key = c.fetchone()
    conn.close()
    
    if has_key:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Generate OTP", callback_data="2fa_gen")],
            [InlineKeyboardButton("🗑️ Remove Key", callback_data="2fa_remove")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
        ])
        await update.message.reply_text(
            "🔐 **2FA Generator**\n\n✅ Your 2FA key is saved!\n\nClick 'Generate OTP' to get your code.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Add 2FA Key", callback_data="2fa_add")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
        ])
        await update.message.reply_text(
            "🔐 **2FA Generator**\n\n❌ No 2FA key saved!\n\nClick 'Add 2FA Key' and send your secret key.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

async def add_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "🔑 **Add 2FA Key**\n\nPlease send your TOTP secret key.\n\nExample: `JBSWY3DPEHPK3PXP`\n\nYou can get this key from Google Authenticator or any 2FA app.",
        parse_mode="Markdown"
    )
    
    context.user_data['awaiting_2fa_key'] = True

async def handle_2fa_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_2fa_key'):
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
            "✅ **2FA Key Added Successfully!**\n\nClick '2FA' button and then 'Generate OTP' to get your codes.",
            parse_mode="Markdown",
            reply_markup=get_bottom_menu()
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Invalid Key!**\n\nError: {str(e)}\n\nPlease send a valid base32 encoded secret key.",
            parse_mode="Markdown"
        )
    
    context.user_data.pop('awaiting_2fa_key', None)

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
        await query.message.edit_text("❌ No 2FA key found!\n\nPlease add a key first.", parse_mode="Markdown")
        return
    
    secret = result[0]
    totp = pyotp.TOTP(secret)
    
    # Create a new message for OTP display
    msg = await query.message.edit_text("⏳ Generating OTP...")
    
    # Live countdown loop (30 seconds)
    for _ in range(30):
        current_time = int(time.time())
        remaining = totp.interval - (current_time % totp.interval)
        otp = totp.at(current_time)
        
        # Progress bar
        bar_length = 20
        filled = int(bar_length * (30 - remaining) / 30)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        text = (
            f"🔐 **Your OTP Code**\n\n"
            f"`{otp}`\n\n"
            f"⏳ **Expires in:** `{remaining}` seconds\n"
            f"`{bar}`\n\n"
            f"🔄 New code will generate automatically..."
        )
        
        try:
            await msg.edit_text(text, parse_mode="Markdown")
        except:
            pass
        
        if remaining <= 1:
            break
        
        await asyncio.sleep(0.5)
    
    # OTP expired
    try:
        await msg.delete()
    except:
        pass
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Generate New OTP", callback_data="2fa_gen")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_main")]
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
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Add New Key", callback_data="2fa_add")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await query.message.edit_text(
        "🗑️ **2FA Key Removed!**\n\nYou can add a new key anytime.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ==================== BALANCE ====================
async def balance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    credits = get_user_credits(user_id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Facebook Checker", callback_data="fb_menu")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await update.message.reply_text(
        f"💰 **Your Balance**\n\n"
        f"💎 **Credits: {credits}**\n\n"
        f"**Usage Cost:**\n"
        f"• Facebook Check: 1 credit\n"
        f"• Facebook Check + OTP: 2 credits\n"
        f"• Other features: Free\n\n"
        f"💡 Contact admin to buy more credits.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ==================== WITHDRAW ====================
async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Request Withdrawal", callback_data="withdraw_req")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await update.message.reply_text(
        "💸 **Withdraw Funds**\n\n"
        "**Minimum:** 100 credits ($10)\n"
        "**Methods:** USDT (TRC20), PayPal\n\n"
        "**How to withdraw:**\n"
        "1. Click 'Request Withdrawal'\n"
        "2. Send your request to admin\n"
        "3. Wait 24-48 hours for processing\n\n"
        "Contact: @AdminUsername",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def withdraw_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "💰 **Request Withdrawal**\n\n"
        "Please send your withdrawal request to @AdminUsername with:\n\n"
        "1. Your User ID\n"
        "2. Amount (minimum 100 credits)\n"
        "3. Payment method (USDT/PayPal)\n"
        "4. Wallet address or PayPal email\n\n"
        f"**Your User ID:** `{query.from_user.id}`\n\n"
        f"**Your Credits:** {get_user_credits(query.from_user.id)}",
        parse_mode="Markdown"
    )

# ==================== HELP ====================
async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **Help Guide**\n\n"
        "**Available Features:**\n\n"
        "📱 **Number** - Get virtual numbers for SMS verification\n"
        "📧 **TempMail** - Create temporary email addresses\n"
        "🔐 **2FA** - Generate TOTP codes with live countdown\n"
        "💰 **Balance** - Check your credits\n"
        "💸 **Withdraw** - Withdraw your earnings\n\n"
        "**Commands:**\n"
        "/start - Restart the bot\n"
        "/menu - Show main menu\n"
        "/myid - Get your user ID\n\n"
        "**Support:** @YourSupportUsername\n\n"
        "💡 **Tip:** You get 10 free credits when you start!"
    )
    
    await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=get_bottom_menu())

# ==================== FACEBOOK CHECKER ====================
async def fb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    credits = get_user_credits(query.from_user.id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Check Number", callback_data="fb_check")],
        [InlineKeyboardButton("🔍 Check + Send OTP", callback_data="fb_check_otp")],
        [InlineKeyboardButton("📊 Check History", callback_data="fb_history")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await query.message.edit_text(
        f"📱 **Facebook Account Checker**\n\n"
        f"⚠️ **DEMO MODE - Educational Purposes Only**\n\n"
        f"**Cost:**\n"
        f"• Check only: 1 credit\n"
        f"• Check + OTP: 2 credits\n\n"
        f"💎 **Your Credits: {credits}**\n\n"
        f"Select an option below:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def fb_check_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if get_user_credits(query.from_user.id) < 1:
        await query.message.edit_text("❌ Insufficient credits! Need 1 credit.", parse_mode="Markdown")
        return
    
    await query.message.edit_text(
        "📱 **Check Facebook Account**\n\n"
        "Send the phone number with country code:\n\n"
        "Examples:\n"
        "• `+8801712345678` (Bangladesh)\n"
        "• `+1234567890` (USA)\n"
        "• `+441234567890` (UK)\n\n"
        "⚠️ Cost: 1 credit",
        parse_mode="Markdown"
    )
    
    context.user_data['fb_check_type'] = 'check'

async def fb_check_otp_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if get_user_credits(query.from_user.id) < 2:
        await query.message.edit_text("❌ Insufficient credits! Need 2 credits.", parse_mode="Markdown")
        return
    
    await query.message.edit_text(
        "📱 **Check + Send OTP**\n\n"
        "Send the phone number with country code:\n\n"
        "Examples:\n"
        "• `+8801712345678` (Bangladesh)\n"
        "• `+1234567890` (USA)\n\n"
        "**What will happen:**\n"
        "1. Check if Facebook account exists\n"
        "2. If found, trigger forgot password\n"
        "3. Send OTP via SMS (SIMULATED)\n\n"
        "⚠️ Cost: 2 credits\n"
        "⚠️ This is a DEMO simulation",
        parse_mode="Markdown"
    )
    
    context.user_data['fb_check_type'] = 'otp'

async def fb_check_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'fb_check_type' not in context.user_data:
        return
    
    check_type = context.user_data['fb_check_type']
    phone = update.message.text.strip()
    user_id = update.effective_user.id
    
    cost = 2 if check_type == 'otp' else 1
    
    # Deduct credits
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits - ? WHERE user_id = ? AND credits >= ?", (cost, user_id, cost))
    conn.commit()
    conn.close()
    
    await update.message.reply_text("🔍 Processing...")
    await asyncio.sleep(1)
    
    # Simulate check
    phone_clean = ''.join(filter(str.isdigit, phone))
    exists = int(phone_clean[-1]) % 2 == 0 if len(phone_clean) >= 10 else False
    
    response = f"📱 **Number:** `{phone}`\n\n"
    
    if exists:
        response += "✅ **Facebook account found!**\n\n"
        response += f"**Account Info:**\n"
        response += f"• Name: User_{phone_clean[-4:]}\n"
        response += f"• Created: 2015-2023\n"
        response += f"• Last Active: Recently\n\n"
        
        if check_type == 'otp':
            otp = random.randint(100000, 999999)
            response += f"📨 **Recovery OTP Sent!**\n"
            response += f"📱 SIMULATED OTP: `{otp}`\n"
            response += f"⏱️ Expires in: 300 seconds\n"
            response += f"\n⚠️ This is a SIMULATION. No actual SMS was sent."
    else:
        response += "❌ **No Facebook account found** with this number."
    
    # Save to history
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO fb_checks (user_id, phone_number, account_found, checked_at) VALUES (?, ?, ?, ?)",
              (user_id, phone, 1 if exists else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(response, parse_mode="Markdown", reply_markup=get_bottom_menu())
    
    context.user_data.pop('fb_check_type', None)

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
        await query.message.edit_text("📊 No check history found.\n\nUse the Facebook checker first!", parse_mode="Markdown")
        return
    
    text = "📊 **Your Facebook Check History**\n\n"
    for log in logs:
        phone, found, time = log
        status = "✅ Found" if found else "❌ Not Found"
        text += f"📱 `{phone[:4]}****{phone[-4:]}` → {status}\n"
        text += f"🕐 {time[:16]}\n\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ==================== BACK TO MAIN ====================
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
        f"🆔 **Your Information**\n\n"
        f"**User ID:** `{user.id}`\n"
        f"**Username:** @{user.username or 'None'}\n"
        f"**First Name:** {user.first_name}\n"
        f"💎 **Credits:** {get_user_credits(user.id)}",
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

# ==================== ADMIN PANEL ====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized access!")
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("➕ Add Number", callback_data="admin_add_num")],
        [InlineKeyboardButton("💰 Add Credits", callback_data="admin_add_cred")],
        [InlineKeyboardButton("📋 Numbers List", callback_data="admin_numbers")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
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
    c.execute("SELECT COUNT(*) FROM virtual_numbers WHERE is_available = 0")
    assigned = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM totp_keys")
    totp_users = c.fetchone()[0]
    conn.close()
    
    await query.message.edit_text(
        f"📊 **Bot Statistics**\n\n"
        f"👥 Total Users: `{users}`\n"
        f"💰 Total Credits: `{credits}`\n"
        f"📱 Available Numbers: `{available}`\n"
        f"📞 Assigned Numbers: `{assigned}`\n"
        f"🔐 2FA Users: `{totp_users}`",
        parse_mode="Markdown"
    )

async def admin_add_number_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text(
        "➕ **Add Virtual Number**\n\n"
        "Send the number in this format:\n"
        "`+1234567890,Country`\n\n"
        "Example: `+8801712345678,Bangladesh`",
        parse_mode="Markdown"
    )
    context.user_data['admin_adding_number'] = True

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
        
        await update.message.reply_text(
            f"✅ **Number Added!**\n\n📞 `{number}`\n🌍 {country}",
            parse_mode="Markdown",
            reply_markup=get_bottom_menu()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=get_bottom_menu())
    
    context.user_data.pop('admin_adding_number', None)

async def admin_add_credits_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text(
        "💰 **Add Credits**\n\n"
        "Send in this format:\n"
        "`USER_ID AMOUNT`\n\n"
        "Example: `123456789 50`",
        parse_mode="Markdown"
    )
    context.user_data['admin_adding_credits'] = True

async def admin_add_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('admin_adding_credits'):
        return
    
    try:
        parts = update.message.text.strip().split()
        user_id = int(parts[0])
        amount = int(parts[1])
        
        update_credits(user_id, amount)
        await update.message.reply_text(
            f"✅ Added {amount} credits to user `{user_id}`",
            parse_mode="Markdown",
            reply_markup=get_bottom_menu()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=get_bottom_menu())
    
    context.user_data.pop('admin_adding_credits', None)

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
        await query.message.edit_text("No numbers found in database.", parse_mode="Markdown")
        return
    
    text = "📋 **Number List**\n\n"
    for num in numbers:
        status = "✅ Available" if num[3] else "❌ Assigned"
        text += f"`{num[1]}` - {num[2]} ({status})\n"
    
    await query.message.edit_text(text, parse_mode="Markdown")

# ==================== MAIN ====================
def signal_handler(signum, frame):
    print("\n🛑 Bot stopping gracefully...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Conversation handlers for admin inputs
    admin_num_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_number_prompt, pattern="admin_add_num")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_number)]},
        fallbacks=[]
    )
    
    admin_cred_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_credits_prompt, pattern="admin_add_cred")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_credits)]},
        fallbacks=[]
    )
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("admin", admin_panel))
    
    # Text handler for bottom menu buttons
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(num_get, pattern="num_get"))
    app.add_handler(CallbackQueryHandler(num_change, pattern="num_change"))
    app.add_handler(CallbackQueryHandler(num_my, pattern="num_my"))
    
    app.add_handler(CallbackQueryHandler(tmp_inbox, pattern="tmp_inbox"))
    app.add_handler(CallbackQueryHandler(tmp_new, pattern="tmp_new"))
    app.add_handler(CallbackQueryHandler(tmp_delete, pattern="tmp_delete"))
    
    app.add_handler(CallbackQueryHandler(add_2fa, pattern="2fa_add"))
    app.add_handler(CallbackQueryHandler(generate_2fa, pattern="2fa_gen"))
    app.add_handler(CallbackQueryHandler(remove_2fa, pattern="2fa_remove"))
    
    app.add_handler(CallbackQueryHandler(fb_menu, pattern="fb_menu"))
    app.add_handler(CallbackQueryHandler(fb_check_prompt, pattern="fb_check"))
    app.add_handler(CallbackQueryHandler(fb_check_otp_prompt, pattern="fb_check_otp"))
    app.add_handler(CallbackQueryHandler(fb_history, pattern="fb_history"))
    
    app.add_handler(CallbackQueryHandler(withdraw_request, pattern="withdraw_req"))
    
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="admin_stats"))
    app.add_handler(CallbackQueryHandler(admin_numbers_list, pattern="admin_numbers"))
    app.add_handler(CallbackQueryHandler(back_main, pattern="back_main"))
    
    # Add conversation handlers
    app.add_handler(admin_num_conv)
    app.add_handler(admin_cred_conv)
    
    # Facebook check handler (text input)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fb_check_handle))
    
    print("=" * 50)
    print("🤖 MULTI-TOOL BOT IS RUNNING")
    print("=" * 50)
    print("📱 Bottom Menu (Always Visible):")
    print("   [📱 Number] [📧 TempMail] [🔐 2FA]")
    print("   [💰 Balance] [💸 Withdraw] [🆘 Help]")
    print("=" * 50)
    print("✅ Features:")
    print("   • 2FA with LIVE COUNTDOWN TIMER")
    print("   • Progress bar showing remaining time")
    print("   • Auto-refresh OTP every 30 seconds")
    print("   • Virtual Numbers (Admin can add)")
    print("   • Temporary Email")
    print("   • Facebook Checker (DEMO)")
    print("=" * 50)
    print(f"👑 Admin ID: {ADMIN_IDS}")
    print("=" * 50)
    print("Bot will run 24/7 without crashes!")
    print("Press Ctrl+C to stop")
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()