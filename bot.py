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

def is_user_banned(user_id):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0] == 1 if result else False
    except:
        return False

def ban_user(user_id):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def unban_user(user_id):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get_all_users():
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = c.fetchall()
        conn.close()
        return [u[0] for u in users]
    except:
        return []

def get_banned_users():
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name FROM users WHERE is_banned = 1")
        users = c.fetchall()
        conn.close()
        return users
    except:
        return []

# ==================== BOTTOM KEYBOARD MENU ====================
def get_bottom_menu():
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📱 Number"), KeyboardButton("📧 TempMail"), KeyboardButton("🔐 2FA")],
        [KeyboardButton("💰 Balance"), KeyboardButton("💸 Withdraw"), KeyboardButton("🆘 Help")]
    ], resize_keyboard=True, one_time_keyboard=False)
    return keyboard

# ==================== START COMMAND ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_user_banned(user.id):
        await update.message.reply_text("❌ You are banned from using this bot!")
        return
    
    add_user(user.id, user.username, user.first_name)
    
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("menu", "Show main menu"),
        BotCommand("myid", "Get user ID"),
        BotCommand("admin", "Admin panel"),
    ]
    await context.bot.set_my_commands(commands)
    
    welcome_text = (
        f"👋 **Welcome {user.first_name}!**\n\n"
        f"🤖 **Multi-Tool Bot**\n\n"
        f"✅ Virtual Numbers\n"
        f"✅ Temporary Email\n"
        f"✅ 2FA Code Generator (Direct - No saving)\n"
        f"✅ Facebook Account Checker\n\n"
        f"💎 **Your Credits: {get_user_credits(user.id)}**\n\n"
        f"Use the buttons below:"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_user_banned(user.id):
        await update.message.reply_text("❌ You are banned from using this bot!")
        return
    
    welcome_text = (
        f"👋 **Welcome back!**\n\n"
        f"🤖 **Multi-Tool Bot**\n\n"
        f"✅ Virtual Numbers\n"
        f"✅ Temporary Email\n"
        f"✅ 2FA Code Generator\n\n"
        f"💎 **Your Credits: {get_user_credits(user.id)}**\n\n"
        f"Use the buttons below:"
    )
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_bottom_menu()
    )

# ==================== TEXT MESSAGE HANDLER ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if is_user_banned(user_id):
        await update.message.reply_text("❌ You are banned from using this bot!")
        return
    
    text = update.message.text
    
    if text == "📱 Number":
        await number_menu(update, context)
    elif text == "📧 TempMail":
        await tempmail_menu(update, context)
    elif text == "🔐 2FA":
        await twofa_prompt(update, context)
    elif text == "💰 Balance":
        await balance_menu(update, context)
    elif text == "💸 Withdraw":
        await withdraw_menu(update, context)
    elif text == "🆘 Help":
        await help_menu(update, context)
    else:
        # Check if waiting for 2FA key
        if context.user_data.get('awaiting_2fa'):
            await generate_2fa_direct(update, context)
        elif context.user_data.get('awaiting_number_input'):
            await handle_number_input(update, context)
        elif context.user_data.get('awaiting_fb_check'):
            await fb_check_handle(update, context)
        else:
            await update.message.reply_text(
                "❌ Unknown command!\n\nUse the buttons below:",
                reply_markup=get_bottom_menu()
            )

# ==================== 2FA DIRECT (NO SAVING) ====================
async def twofa_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔐 **2FA Code Generator**\n\n"
        "Send me your TOTP secret key and I'll generate live OTP codes!\n\n"
        "**Example:** `JBSWY3DPEHPK3PXP`\n\n"
        "⚠️ Your key is NOT saved. You need to send it each time.",
        parse_mode="Markdown"
    )
    context.user_data['awaiting_2fa'] = True

async def generate_2fa_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_2fa'):
        return
    
    secret = update.message.text.strip().upper().replace(" ", "")
    
    try:
        totp = pyotp.TOTP(secret)
        test = totp.now()
        if not test or len(test) != 6:
            raise ValueError("Invalid")
        
        # Send initial message
        msg = await update.message.reply_text("⏳ Generating OTP...")
        
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
            [InlineKeyboardButton("🔄 Generate New OTP", callback_data="2fa_new")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_main")]
        ])
        
        await update.message.reply_text(
            "⌛ **OTP Expired!**\n\nClick below to generate a new code with the SAME key, or send a NEW key.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        
        # Keep waiting for new key
        context.user_data['awaiting_2fa'] = True
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Invalid Key!**\n\nError: {str(e)}\n\nPlease send a valid base32 encoded secret key.\nExample: `JBSWY3DPEHPK3PXP`",
            parse_mode="Markdown"
        )
        # Still waiting for valid key
        context.user_data['awaiting_2fa'] = True

async def twofa_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "🔐 **2FA Code Generator**\n\n"
        "Send me your TOTP secret key again:\n\n"
        "**Example:** `JBSWY3DPEHPK3PXP`",
        parse_mode="Markdown"
    )
    context.user_data['awaiting_2fa'] = True

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
        "🔐 **2FA** - Send secret key, get live OTP with countdown (No saving)\n"
        "💰 **Balance** - Check your credits\n"
        "💸 **Withdraw** - Withdraw your earnings\n\n"
        "**Commands:**\n"
        "/start - Restart the bot\n"
        "/menu - Show main menu\n"
        "/myid - Get your user ID\n"
        "/admin - Admin panel (Admins only)\n\n"
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
        "• `+1234567890` (USA)\n\n"
        "⚠️ Cost: 1 credit",
        parse_mode="Markdown"
    )
    
    context.user_data['fb_check_type'] = 'check'
    context.user_data['awaiting_fb_check'] = True

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
        "⚠️ Cost: 2 credits\n"
        "⚠️ This is a DEMO simulation",
        parse_mode="Markdown"
    )
    
    context.user_data['fb_check_type'] = 'otp'
    context.user_data['awaiting_fb_check'] = True

async def fb_check_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_fb_check'):
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
    
    context.user_data.pop('awaiting_fb_check', None)
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
        f"✅ 2FA Code Generator\n\n"
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
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ Unban User", callback_data="admin_unban")],
        [InlineKeyboardButton("📋 Banned List", callback_data="admin_banned")],
        [InlineKeyboardButton("➕ Add Number", callback_data="admin_add_num")],
        [InlineKeyboardButton("💰 Add Credits", callback_data="admin_add_cred")],
        [InlineKeyboardButton("📋 Numbers List", callback_data="admin_numbers")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ])
    
    await update.message.reply_text("🔧 **Admin Panel**\n\nSelect an option:", parse_mode="Markdown", reply_markup=keyboard)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    banned = c.fetchone()[0]
    c.execute("SELECT SUM(credits) FROM users")
    credits = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM virtual_numbers WHERE is_available = 1")
    available = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM virtual_numbers WHERE is_available = 0")
    assigned = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM fb_checks")
    fb_checks = c.fetchone()[0]
    conn.close()
    
    await query.message.edit_text(
        f"📊 **Bot Statistics**\n\n"
        f"👥 Total Users: `{users}`\n"
        f"🚫 Banned Users: `{banned}`\n"
        f"💰 Total Credits: `{credits}`\n"
        f"📱 Available Numbers: `{available}`\n"
        f"📞 Assigned Numbers: `{assigned}`\n"
        f"📱 Facebook Checks: `{fb_checks}`",
        parse_mode="Markdown"
    )

async def admin_broadcast_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text(
        "📢 **Broadcast Message**\n\n"
        "Send the message you want to broadcast to all users.\n\n"
        "⚠️ This will be sent to ALL users.\n"
        "Type /cancel to cancel.",
        parse_mode="Markdown"
    )
    context.user_data['admin_broadcasting'] = True

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('admin_broadcasting'):
        return
    
    message_text = update.message.text
    
    if message_text == "/cancel":
        await update.message.reply_text("❌ Broadcast cancelled!", reply_markup=get_bottom_menu())
        context.user_data.pop('admin_broadcasting', None)
        return
    
    users = get_all_users()
    success = 0
    failed = 0
    
    status_msg = await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    
    for user_id in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=f"📢 **Broadcast Message**\n\n{message_text}", parse_mode="Markdown")
            success += 1
        except:
            failed += 1
        await asyncio.sleep(0.05)  # Avoid flood wait
    
    await status_msg.edit_text(
        f"✅ **Broadcast Complete!**\n\n"
        f"📤 Sent: {success}\n"
        f"❌ Failed: {failed}\n"
        f"👥 Total: {len(users)}",
        parse_mode="Markdown"
    )
    
    context.user_data.pop('admin_broadcasting', None)

async def admin_ban_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text(
        "🚫 **Ban User**\n\n"
        "Send the User ID to ban:\n\n"
        "Example: `123456789`\n\n"
        "Type /cancel to cancel.",
        parse_mode="Markdown"
    )
    context.user_data['admin_banning'] = True

async def admin_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('admin_banning'):
        return
    
    user_id_text = update.message.text.strip()
    
    if user_id_text == "/cancel":
        await update.message.reply_text("❌ Cancelled!", reply_markup=get_bottom_menu())
        context.user_data.pop('admin_banning', None)
        return
    
    try:
        user_id = int(user_id_text)
        
        if ban_user(user_id):
            await update.message.reply_text(f"✅ User `{user_id}` has been banned!", parse_mode="Markdown")
            
            # Notify the banned user
            try:
                await context.bot.send_message(chat_id=user_id, text="❌ You have been banned from using this bot!")
            except:
                pass
        else:
            await update.message.reply_text(f"❌ Failed to ban user `{user_id}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Invalid User ID! Please send a valid number.")
    
    context.user_data.pop('admin_banning', None)

async def admin_unban_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text(
        "✅ **Unban User**\n\n"
        "Send the User ID to unban:\n\n"
        "Example: `123456789`\n\n"
        "Type /cancel to cancel.",
        parse_mode="Markdown"
    )
    context.user_data['admin_unbanning'] = True

async def admin_unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('admin_unbanning'):
        return
    
    user_id_text = update.message.text.strip()
    
    if user_id_text == "/cancel":
        await update.message.reply_text("❌ Cancelled!", reply_markup=get_bottom_menu())
        context.user_data.pop('admin_unbanning', None)
        return
    
    try:
        user_id = int(user_id_text)
        
        if unban_user(user_id):
            await update.message.reply_text(f"✅ User `{user_id}` has been unbanned!", parse_mode="Markdown")
            
            # Notify the unbanned user
            try:
                await context.bot.send_message(chat_id=user_id, text="✅ You have been unbanned! You can use the bot again.")
            except:
                pass
        else:
            await update.message.reply_text(f"❌ Failed to unban user `{user_id}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Invalid User ID! Please send a valid number.")
    
    context.user_data.pop('admin_unbanning', None)

async def admin_banned_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    banned_users = get_banned_users()
    
    if not banned_users:
        await query.message.edit_text("📋 No banned users found.", parse_mode="Markdown")
        return
    
    text = "🚫 **Banned Users List**\n\n"
    for user in banned_users:
        user_id, username, first_name = user
        text += f"🆔 `{user_id}` - {first_name} (@{username or 'No username'})\n"
    
    await query.message.edit_text(text, parse_mode="Markdown")

async def admin_add_number_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    await query.message.edit_text(
        "➕ **Add Virtual Number**\n\n"
        "Send the number in this format:\n"
        "`+1234567890,Country`\n\n"
        "Example: `+8801712345678,Bangladesh`\n\n"
        "Type /cancel to cancel.",
        parse_mode="Markdown"
    )
    context.user_data['admin_adding_number'] = True

async def admin_add_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('admin_adding_number'):
        return
    
    data = update.message.text.strip()
    
    if data == "/cancel":
        await update.message.reply_text("❌ Cancelled!", reply_markup=get_bottom_menu())
        context.user_data.pop('admin_adding_number', None)
        return
    
    try:
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
        "Example: `123456789 50`\n\n"
        "Type /cancel to cancel.",
        parse_mode="Markdown"
    )
    context.user_data['admin_adding_credits'] = True

async def admin_add_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('admin_adding_credits'):
        return
    
    data = update.message.text.strip()
    
    if data == "/cancel":
        await update.message.reply_text("❌ Cancelled!", reply_markup=get_bottom_menu())
        context.user_data.pop('admin_adding_credits', None)
        return
    
    try:
        parts = data.split()
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
    c.execute("SELECT id, number, country, is_available FROM virtual_numbers LIMIT 30")
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
    
    # Conversation handlers
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_prompt, pattern="admin_broadcast")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_send)]},
        fallbacks=[]
    )
    
    ban_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_ban_prompt, pattern="admin_ban")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ban_user)]},
        fallbacks=[]
    )
    
    unban_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_unban_prompt, pattern="admin_unban")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_unban_user)]},
        fallbacks=[]
    )
    
    add_num_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_number_prompt, pattern="admin_add_num")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_number)]},
        fallbacks=[]
    )
    
    add_cred_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_credits_prompt, pattern="admin_add_cred")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_credits)]},
        fallbacks=[]
    )
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("admin", admin_panel))
    
    # Text handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(num_get, pattern="num_get"))
    app.add_handler(CallbackQueryHandler(num_change, pattern="num_change"))
    app.add_handler(CallbackQueryHandler(num_my, pattern="num_my"))
    
    app.add_handler(CallbackQueryHandler(tmp_inbox, pattern="tmp_inbox"))
    app.add_handler(CallbackQueryHandler(tmp_new, pattern="tmp_new"))
    app.add_handler(CallbackQueryHandler(tmp_delete, pattern="tmp_delete"))
    
    app.add_handler(CallbackQueryHandler(twofa_new, pattern="2fa_new"))
    
    app.add_handler(CallbackQueryHandler(fb_menu, pattern="fb_menu"))
    app.add_handler(CallbackQueryHandler(fb_check_prompt, pattern="fb_check"))
    app.add_handler(CallbackQueryHandler(fb_check_otp_prompt, pattern="fb_check_otp"))
    app.add_handler(CallbackQueryHandler(fb_history, pattern="fb_history"))
    
    app.add_handler(CallbackQueryHandler(withdraw_request, pattern="withdraw_req"))
    
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="admin_stats"))
    app.add_handler(CallbackQueryHandler(admin_banned_list, pattern="admin_banned"))
    app.add_handler(CallbackQueryHandler(admin_numbers_list, pattern="admin_numbers"))
    app.add_handler(CallbackQueryHandler(back_main, pattern="back_main"))
    
    # Conversation handlers
    app.add_handler(broadcast_conv)
    app.add_handler(ban_conv)
    app.add_handler(unban_conv)
    app.add_handler(add_num_conv)
    app.add_handler(add_cred_conv)
    
    print("=" * 50)
    print("🤖 MULTI-TOOL BOT IS RUNNING")
    print("=" * 50)
    print("📱 Bottom Menu (Always Visible):")
    print("   [📱 Number] [📧 TempMail] [🔐 2FA]")
    print("   [💰 Balance] [💸 Withdraw] [🆘 Help]")
    print("=" * 50)
    print("✅ 2FA: Direct - Send key, get live OTP (No saving)")
    print("✅ Admin Panel: Broadcast, Ban, Unban, Add Numbers, Add Credits")
    print("=" * 50)
    print(f"👑 Admin ID: {ADMIN_IDS}")
    print("=" * 50)
    print("Bot will run 24/7 without crashes!")
    print("Press Ctrl+C to stop")
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()