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
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")

# Database setup
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, 
                  join_date TEXT, is_banned BOOLEAN DEFAULT 0, credits INTEGER DEFAULT 0)''')
    
    # 2FA keys table
    c.execute('''CREATE TABLE IF NOT EXISTS totp_keys
                 (user_id INTEGER, secret_key TEXT, created_at TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    # Temp emails table
    c.execute('''CREATE TABLE IF NOT EXISTS temp_emails
                 (user_id INTEGER, email TEXT, created_at TEXT, 
                  last_checked TEXT, FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    # Facebook checker logs
    c.execute('''CREATE TABLE IF NOT EXISTS fb_checks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                  phone_number TEXT, status TEXT, account_found BOOLEAN, 
                  otp_sent BOOLEAN, checked_at TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    # User usage stats
    c.execute('''CREATE TABLE IF NOT EXISTS user_usage
                 (user_id INTEGER, feature TEXT, used_at TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    conn.commit()
    conn.close()

init_db()

# Facebook Checker - DEMO/SIMULATION ONLY
class FacebookChecker:
    @staticmethod
    def check_account(phone_number):
        """
        DEMO VERSION - Simulates Facebook account checking
        For real implementation, you would need:
        1. Facebook's official API (requires approval)
        2. Or reverse-engineered endpoints (against ToS)
        
        This is a SIMULATION for educational purposes only
        """
        try:
            # Clean phone number
            phone = ''.join(filter(str.isdigit, phone_number))
            if len(phone) < 10:
                return {
                    'status': 'invalid',
                    'account_found': False,
                    'message': '❌ Invalid phone number format. Use country code + number.'
                }
            
            # SIMULATION: Use number patterns to determine "existence"
            # In real implementation, this would be an actual API call to Facebook
            last_digit = int(phone[-1])
            sum_digits = sum(int(d) for d in phone) % 10
            
            # Simulate account existence (50% chance for demo)
            account_exists = (last_digit % 2 == 0) or (sum_digits > 5)
            
            if account_exists:
                return {
                    'status': 'exists',
                    'account_found': True,
                    'message': '✅ Facebook account FOUND!',
                    'can_recover': True,
                    'recovery_methods': ['sms', 'email'],
                    'account_info': {
                        'name': f'User_{phone[-4:]}',
                        'created': '2015-2023',
                        'last_active': 'Recently'
                    }
                }
            else:
                return {
                    'status': 'not_exists',
                    'account_found': False,
                    'message': '❌ No Facebook account found with this number.',
                    'can_recover': False
                }
                
        except Exception as e:
            return {
                'status': 'error',
                'account_found': False,
                'message': f'⚠️ Error: {str(e)}',
                'can_recover': False
            }
    
    @staticmethod
    def send_recovery_otp(phone_number):
        """
        DEMO VERSION - Simulates sending OTP via SMS
        Real implementation would require:
        1. Facebook's password reset endpoint
        2. SMS gateway integration
        3. Handling rate limits and captchas
        
        This is a SIMULATION for educational purposes only
        """
        try:
            # Clean phone
            phone = ''.join(filter(str.isdigit, phone_number))
            
            # Generate mock OTP
            mock_otp = ''.join(random.choices(string.digits, k=6))
            
            # SIMULATION: Always "succeeds" for demo
            return {
                'success': True,
                'otp': mock_otp,
                'message': f'📱 OTP sent to {phone_number[:4]}****{phone_number[-2:]}',
                'expires_in': 300,  # 5 minutes
                'note': '⚠️ This is a SIMULATION. No actual SMS was sent.'
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Failed to send OTP: {str(e)}'
            }

# Admin functions
def is_admin(user_id):
    return user_id in ADMIN_IDS

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel with controls"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized access!")
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
    
    await update.message.reply_text(
        "🔧 **Admin Panel**\n\nWelcome to admin control panel.\n\nSelect an option:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # Get stats
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
    
    c.execute("SELECT COUNT(*) FROM fb_checks WHERE account_found = 1")
    accounts_found = c.fetchone()[0]
    
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
        f"✅ **Accounts Found:** `{accounts_found}`\n"
        f"💰 **Total Credits:** `{total_credits}`\n\n"
        f"🤖 **Bot Status:** 🟢 Running\n"
        f"⚠️ **Note:** Facebook checker is DEMO mode"
    )
    
    await query.message.edit_text(stats_text, parse_mode="Markdown")

async def admin_fb_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View Facebook check logs"""
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

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main menu with buttons"""
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
    
    # Add admin button if user is admin
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
    
    if isinstance(message, str):
        await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await message.edit_text(welcome_text, parse_mode="Markdown", reply_markup=keyboard)

def get_user_credits(user_id):
    """Get user credits from database"""
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

async def facebook_checker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Facebook checker menu"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Check Single Number", callback_data="fb_check_single")],
        [InlineKeyboardButton("🔍 Check + Send OTP", callback_data="fb_check_otp")],
        [InlineKeyboardButton("📊 Bulk Check", callback_data="fb_bulk")],
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
        "• Bulk number checking\n"
        "• Check history\n\n"
        "**Cost:** 1 credit per check\n"
        "**Your Credits:** {}\n\n"
        "🔴 **Important:** This is a simulation. No actual Facebook accounts are accessed or modified.".format(get_user_credits(query.from_user.id)),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def fb_check_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single number check"""
    query = update.callback_query
    await query.answer()
    
    # Check credits
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
    """Check and send OTP"""
    query = update.callback_query
    await query.answer()
    
    # Check credits
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
    """Handle Facebook check"""
    if 'awaiting_fb_check' not in context.user_data:
        return
    
    check_type = context.user_data['awaiting_fb_check']
    phone = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Deduct credits
    cost = 2 if check_type == 'with_otp' else 1
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits - ? WHERE user_id = ?", (cost, user_id))
    conn.commit()
    conn.close()
    
    status_msg = await update.message.reply_text("🔍 Processing...")
    
    # Perform check
    result = FacebookChecker.check_account(phone)
    
    # Prepare response
    response = f"📱 **Phone:** `{phone}`\n\n"
    response += f"{result['message']}\n\n"
    
    if result['account_found']:
        response += "**Account Details:**\n"
        response += f"• Name: {result.get('account_info', {}).get('name', 'Unknown')}\n"
        response += f"• Created: {result.get('account_info', {}).get('created', 'Unknown')}\n"
        response += f"• Last Active: {result.get('account_info', {}).get('last_active', 'Unknown')}\n\n"
        
        if check_type == 'with_otp' and result['can_recover']:
            # Send OTP (SIMULATED)
            await status_msg.edit_text("📨 Sending recovery OTP...")
            await asyncio.sleep(2)
            
            otp_result = FacebookChecker.send_recovery_otp(phone)
            
            response += "**Recovery OTP:**\n"
            response += f"{otp_result['message']}\n"
            if otp_result['success']:
                response += f"📱 **SIMULATED OTP:** `{otp_result['otp']}`\n"
                response += f"⏱️ Expires in: {otp_result['expires_in']} seconds\n"
                response += "\n⚠️ **This is a SIMULATION** - No actual OTP was sent to the phone number.\n"
                response += "In a real implementation, Facebook would send an SMS to the number."
            
            otp_sent = otp_result['success']
        else:
            otp_sent = False
            if check_type == 'with_otp':
                response += "⚠️ Recovery not available for this account.\n"
    else:
        otp_sent = False
    
    # Log to database
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO fb_checks VALUES (?, ?, ?, ?, ?, ?, ?)",
              (None, user_id, phone, result['status'], 
               1 if result['account_found'] else 0,
               1 if otp_sent else 0,
               datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    # Log usage
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO user_usage VALUES (?, ?, ?)",
              (user_id, f'fb_check_{check_type}', datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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
    """Show user's check history"""
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
    """Information about Facebook checker"""
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
        "**Real Implementation Challenges:**\n"
        "• Facebook's official API requires business approval\n"
        "• Reverse-engineering violates ToS\n"
        "• Rate limits and captchas\n"
        "• Legal restrictions in many countries\n\n"
        "**Educational Purpose:**\n"
        "This demonstrates how account checking systems work conceptually.\n\n"
        "For real Facebook account recovery, visit:\n"
        "https://www.facebook.com/login/identify"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="get_number")]
    ])
    
    await query.message.edit_text(info_text, parse_mode="Markdown", reply_markup=keyboard)

async def get_number_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get number menu"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇸 USA Number", callback_data="number_usa"),
         InlineKeyboardButton("🇬🇧 UK Number", callback_data="number_uk")],
        [InlineKeyboardButton("🇨🇦 Canada", callback_data="number_ca"),
         InlineKeyboardButton("🇦🇺 Australia", callback_data="number_au")],
        [InlineKeyboardButton("📱 Facebook Checker", callback_data="fb_checker")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        "📱 **Get Virtual Number**\n\n"
        "Select a country to get a virtual phone number:\n\n"
        "⚠️ Numbers are for verification purposes only.\n\n"
        "🔍 Also check Facebook account status with our checker!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# Placeholder functions for other features
async def get_tempmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await query.message.edit_text("Temp mail feature coming soon!")

async def two_fa_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await query.message.edit_text("2FA feature coming soon!")

async def balances_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await query.message.edit_text("Balances feature coming soon!")

async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await query.message.edit_text("Withdraw feature coming soon!")

async def support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await query.message.edit_text("Support feature coming soon!")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user = update.effective_user
    
    # Save user to database
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?, ?, ?)",
              (user.id, user.username, user.first_name, 
               datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0, 10))  # Give 10 free credits
    conn.commit()
    conn.close()
    
    # Set bot commands
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("menu", "Show main menu"),
        BotCommand("help", "Help and support"),
        BotCommand("myid", "Get your user ID"),
    ]
    await context.bot.set_my_commands(commands)
    
    await update.message.reply_text(
        f"👋 Welcome {user.first_name}!\n\n"
        f"🤖 **Multi-Tool Bot**\n\n"
        f"I can help you with:\n"
        f"✓ Facebook Account Checker (DEMO)\n"
        f"✓ Temporary Email\n"
        f"✓ 2FA Code Generator\n"
        f"✓ And more!\n\n"
        f"💎 You've received 10 free credits!\n\n"
        f"Use /menu to get started!",
        parse_mode="Markdown"
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu command"""
    await main_menu(update, context)

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get user ID"""
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
    """Help command"""
    help_text = (
        "📖 **Bot Help Guide**\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/menu - Show main menu\n"
        "/myid - Get your user ID\n"
        "/help - Show this message\n\n"
        "**Features:**\n"
        "📱 **Facebook Checker** - Check accounts (DEMO)\n"
        "🔐 **2FA** - Generate TOTP codes\n"
        "📧 **Temp Mail** - Temporary email addresses\n"
        "💰 **Balances** - Check credits\n"
        "💸 **Withdraw** - Withdraw funds\n\n"
        "**⚠️ DISCLAIMER:**\n"
        "Facebook checker is a DEMO/SIMULATION.\n"
        "No real Facebook accounts are accessed.\n\n"
        "**Need help?** Contact @support_username"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

def main():
    """Main function to run the bot"""
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add conversation handlers
    fb_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(fb_check_single, pattern="fb_check_single"),
            CallbackQueryHandler(fb_check_with_otp, pattern="fb_check_otp")
        ],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fb_check)]},
        fallbacks=[]
    )
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("help", help_command))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(main_menu, pattern="main_menu"))
    app.add_handler(CallbackQueryHandler(get_number_menu, pattern="get_number"))
    app.add_handler(CallbackQueryHandler(facebook_checker_menu, pattern="fb_checker"))
    app.add_handler(CallbackQueryHandler(fb_history, pattern="fb_history"))
    app.add_handler(CallbackQueryHandler(fb_info, pattern="fb_info"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="admin_panel"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="admin_stats"))
    app.add_handler(CallbackQueryHandler(admin_fb_logs, pattern="admin_fb_logs"))
    
    # Add conversation handlers
    app.add_handler(fb_conv_handler)
    
    print("🤖 Multi-Tool Bot is running...")
    print("⚠️ Facebook Checker is in DEMO MODE")
    print("⚠️ No actual Facebook data is accessed")
    print("Admin IDs:", ADMIN_IDS)
    print("Press Ctrl+C to stop")
    
    app.run_polling()

if __name__ == "__main__":
    main()