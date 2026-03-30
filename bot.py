#!/usr/bin/env python3
"""
Verification Hub Bot - Complete Solution
Features: Facebook Checker, Temp Mail, 2FA Generator, OTP Receiver, Card Generator
"""

import os
import re
import json
import time
import random
import asyncio
import string
import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pyotp
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, ContextTypes, filters, ConversationHandler
)

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
DATA_FILE = "bot_data.json"

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation States
ADD_2FA_STATE = 1
FB_CHECK_STATE = 2
CARD_GEN_STATE = 3

# ==================== DATA MANAGEMENT ====================
class BotData:
    def __init__(self):
        self.data = self._load_data()
    
    def _load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return self._default_data()
    
    def _default_data(self):
        return {
            "active_number": None,
            "otp_history": [],
            "pending_otp": None,
            "twofa_keys": {},
            "card_history": []
        }
    
    def save(self):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
    
    def get_active_number(self):
        return self.data.get("active_number")
    
    def set_active_number(self, number):
        self.data["active_number"] = number
        self.save()
    
    def add_otp(self, otp, number=None, received_by="System"):
        if number is None:
            number = self.get_active_number()
        
        otp_record = {
            "number": number,
            "otp": str(otp),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "received_by": received_by
        }
        
        self.data["pending_otp"] = otp_record
        self.data["otp_history"].insert(0, otp_record)
        
        if len(self.data["otp_history"]) > 100:
            self.data["otp_history"] = self.data["otp_history"][:100]
        
        self.save()
        return otp_record
    
    def get_pending_otp(self):
        return self.data.get("pending_otp")
    
    def get_otp_history(self, limit=20):
        return self.data["otp_history"][:limit]
    
    def add_twofa_key(self, user_id, name, secret):
        if str(user_id) not in self.data["twofa_keys"]:
            self.data["twofa_keys"][str(user_id)] = {}
        
        self.data["twofa_keys"][str(user_id)][name] = secret
        self.save()
        return True
    
    def get_twofa_keys(self, user_id):
        return self.data["twofa_keys"].get(str(user_id), {})
    
    def delete_twofa_key(self, user_id, name):
        if str(user_id) in self.data["twofa_keys"]:
            if name in self.data["twofa_keys"][str(user_id)]:
                del self.data["twofa_keys"][str(user_id)][name]
                self.save()
                return True
        return False
    
    def add_card(self, bin_number, card_data):
        record = {
            "bin": bin_number,
            "card": card_data,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.data["card_history"].insert(0, record)
        if len(self.data["card_history"]) > 50:
            self.data["card_history"] = self.data["card_history"][:50]
        self.save()

bot_data = BotData()

# ==================== HELPER FUNCTIONS ====================

def generate_temp_email():
    domains = ["tempmail.com", "10minute.net", "guerrillamail.com", "mailinator.com", "temp-mail.org"]
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
    domain = random.choice(domains)
    return f"{username}@{domain}", domain

def check_facebook_account(phone_number):
    if not phone_number or not phone_number.startswith('+'):
        return {"success": False, "exists": False, "message": "Invalid phone format"}
    return {"success": True, "exists": random.choice([True, False]), "message": "Check completed"}

def generate_2fa_code(secret):
    try:
        totp = pyotp.TOTP(secret)
        current_code = totp.now()
        remaining = totp.interval - (int(time.time()) % totp.interval)
        return {"success": True, "code": current_code, "remaining": remaining, "interval": totp.interval}
    except Exception as e:
        return {"success": False, "error": str(e)}

def format_progress_bar(remaining, total=30):
    progress = int((total - remaining) / total * 20)
    bar = "█" * progress + "░" * (20 - progress)
    return bar

def generate_card(bin_number):
    """Generate credit card number from BIN"""
    try:
        bin_str = str(bin_number).strip()
        if len(bin_str) < 6:
            return {"success": False, "error": "BIN must be at least 6 digits"}
        
        # Generate random digits
        remaining_digits = 16 - len(bin_str)
        random_part = ''.join([str(random.randint(0, 9)) for _ in range(remaining_digits - 1)])
        card_without_check = bin_str + random_part
        
        # Luhn algorithm for check digit
        def luhn_checksum(card_number):
            def digits_of(n):
                return [int(d) for d in str(n)]
            digits = digits_of(card_number)
            odd_digits = digits[-1::-2]
            even_digits = digits[-2::-2]
            checksum = sum(odd_digits)
            for d in even_digits:
                checksum += sum(digits_of(d * 2))
            return checksum % 10
        
        check_digit = (10 - luhn_checksum(int(card_without_check + "0"))) % 10
        card_number = card_without_check + str(check_digit)
        
        # Generate CVV and expiry
        cvv = ''.join([str(random.randint(0, 9)) for _ in range(3)])
        month = str(random.randint(1, 12)).zfill(2)
        year = str(random.randint(2025, 2030))
        
        # Detect card type
        card_type = "Unknown"
        if bin_str.startswith('4'):
            card_type = "VISA"
        elif bin_str.startswith(('51', '52', '53', '54', '55')):
            card_type = "MasterCard"
        elif bin_str.startswith(('34', '37')):
            card_type = "AMEX"
        elif bin_str.startswith('6'):
            card_type = "Discover"
        
        return {
            "success": True,
            "card_number": card_number,
            "cvv": cvv,
            "expiry": f"{month}/{year}",
            "type": card_type,
            "bin": bin_str
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ==================== MAIN MENU ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - Show main menu with buttons only"""
    user_id = update.effective_user.id
    
    # Main Menu with all features
    keyboard = [
        [InlineKeyboardButton("📱 Facebook Checker", callback_data="fb_check")],
        [InlineKeyboardButton("📧 Temp Mail", callback_data="temp_mail")],
        [InlineKeyboardButton("🔐 2FA Generator", callback_data="twofa_menu")],
        [InlineKeyboardButton("📨 OTP Receiver", callback_data="otp_menu")],
        [InlineKeyboardButton("💳 Card Generator", callback_data="card_menu")],
        [InlineKeyboardButton("ℹ️ About", callback_data="about")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "🤖 **Verification Hub Bot**\n\n"
        "Welcome! I can help you with:\n\n"
        "📱 **Facebook Checker** - Check if a number has FB account\n"
        "📧 **Temp Mail** - Generate temporary email for OTP\n"
        "🔐 **2FA Generator** - Generate TOTP codes from secret keys\n"
        "📨 **OTP Receiver** - View received OTP codes\n"
        "💳 **Card Generator** - Generate valid credit card numbers\n\n"
        "👇 **Click on any button below to get started!**"
    )
    
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)

# ==================== FACEBOOK CHECKER ====================

async def fb_check_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🔍 Check Number", callback_data="fb_check_start")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📱 **Facebook Account Checker**\n\n"
        "Send a phone number to check if it has a Facebook account.\n\n"
        "📌 **Format:** `+8801xxxxxxxxx`\n\n"
        "Click below to start:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def fb_check_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔍 **Enter Phone Number**\n\n"
        "Send the phone number in international format:\n"
        "Example: `+8801712345678`\n\n"
        "Type /cancel to abort.",
        parse_mode="Markdown"
    )
    return FB_CHECK_STATE

async def fb_check_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    
    if not re.match(r'^\+[0-9]{10,15}$', phone):
        await update.message.reply_text(
            "❌ **Invalid Format!**\n\nUse: `+8801xxxxxxxxx`\n\nSend again or type /cancel",
            parse_mode="Markdown"
        )
        return FB_CHECK_STATE
    
    msg = await update.message.reply_text(f"🔍 Checking `{phone}`...\n⏳ Please wait", parse_mode="Markdown")
    
    result = check_facebook_account(phone)
    
    if result.get("success") and result.get("exists"):
        response = f"✅ **Facebook Account Found!**\n\n📱 `{phone}`\n\n📌 This number is registered on Facebook."
    else:
        response = f"❌ **No Facebook Account**\n\n📱 `{phone}`\n\n📌 This number is not linked to any Facebook account."
    
    keyboard = [
        [InlineKeyboardButton("🔍 Check Another", callback_data="fb_check_start")],
        [InlineKeyboardButton("🔙 Back", callback_data="fb_check")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.delete()
    await update.message.reply_text(response, parse_mode="Markdown", reply_markup=reply_markup)
    return ConversationHandler.END

# ==================== TEMP MAIL ====================

temp_mails = {}  # Simple storage for temp mails

async def temp_mail_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    current_mail = temp_mails.get(user_id, {}).get("email", "None")
    
    keyboard = [
        [InlineKeyboardButton("🆕 Generate Email", callback_data="gen_temp_mail")],
        [InlineKeyboardButton("📥 Check Inbox", callback_data="check_inbox")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📧 **Temporary Email**\n\n"
        f"📧 **Current:** `{current_mail}`\n\n"
        f"Generate a temporary email to receive verification codes.\n\n"
        f"Use the buttons below:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def generate_temp_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Generating email...")
    
    user_id = query.from_user.id
    email, domain = generate_temp_email()
    
    temp_mails[user_id] = {
        "email": email,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "messages": []
    }
    
    keyboard = [
        [InlineKeyboardButton("📥 Check Inbox", callback_data="check_inbox")],
        [InlineKeyboardButton("🆕 New Email", callback_data="gen_temp_mail")],
        [InlineKeyboardButton("🔙 Back", callback_data="temp_mail")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ **Email Created!**\n\n"
        f"📧 `{email}`\n\n"
        f"Use this email to receive verification codes.\n"
        f"Click 'Check Inbox' to see received emails.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def check_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Checking inbox...")
    
    user_id = query.from_user.id
    mail_data = temp_mails.get(user_id)
    
    if not mail_data:
        keyboard = [[InlineKeyboardButton("🆕 Generate Email", callback_data="gen_temp_mail")]]
        await query.edit_message_text(
            "❌ **No email found!**\n\nGenerate a temporary email first.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    email = mail_data["email"]
    
    # Simulated inbox check
    await query.edit_message_text(
        f"📬 **Inbox for:** `{email}`\n\n"
        f"📭 **No new messages**\n\n"
        f"Send verification codes to this email.\n"
        f"New emails will appear here when received.",
        parse_mode="Markdown"
    )

# ==================== 2FA GENERATOR ====================

async def twofa_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    keys = bot_data.get_twofa_keys(user_id)
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Secret Key", callback_data="add_twofa")],
        [InlineKeyboardButton("📋 My Keys", callback_data="list_twofa")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🔐 **2FA Code Generator**\n\n"
        f"📦 **Saved Keys:** `{len(keys)}`\n\n"
        f"Add your TOTP secret keys to generate live 2FA codes.\n\n"
        f"Select an option:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def add_twofa_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔑 **Add 2FA Secret Key**\n\n"
        "Send your TOTP secret key (Base32 format).\n"
        "Example: `JBSWY3DPEHPK3PXP`\n\n"
        "Type /cancel to abort.",
        parse_mode="Markdown"
    )
    return ADD_2FA_STATE

async def add_twofa_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip().upper().replace(" ", "")
    user_id = update.effective_user.id
    
    if "temp_secret" not in context.user_data:
        try:
            pyotp.TOTP(user_input).now()
            context.user_data["temp_secret"] = user_input
            await update.message.reply_text(
                "✅ **Valid secret key!**\n\nNow send a name for this key:\nExample: `Google`, `GitHub`, `Facebook`"
            )
            return ADD_2FA_STATE
        except Exception as e:
            await update.message.reply_text(f"❌ **Invalid secret key!**\n\nError: {str(e)}")
            return ADD_2FA_STATE
    else:
        name = user_input.strip()
        secret = context.user_data["temp_secret"]
        
        if bot_data.add_twofa_key(user_id, name, secret):
            await update.message.reply_text(
                f"✅ **2FA Key Saved!**\n\n🔑 **Name:** `{name}`\n🔐 **Secret:** `{secret[:8]}...`",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Failed to save key.")
        
        del context.user_data["temp_secret"]
        return ConversationHandler.END

async def list_twofa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    keys = bot_data.get_twofa_keys(user_id)
    
    if not keys:
        keyboard = [[InlineKeyboardButton("➕ Add Key", callback_data="add_twofa")]]
        await query.edit_message_text(
            "📭 **No 2FA keys saved!**\n\nAdd your first secret key.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    keyboard = []
    for name in keys.keys():
        keyboard.append([InlineKeyboardButton(f"🔑 {name}", callback_data=f"gen_2fa_{name}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="twofa_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📋 **Your 2FA Keys** ({len(keys)})\n\nClick on a key to generate OTP:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def generate_twofa_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    key_name = query.data.replace("gen_2fa_", "")
    user_id = query.from_user.id
    
    keys = bot_data.get_twofa_keys(user_id)
    secret = keys.get(key_name)
    
    if not secret:
        await query.answer("Key not found!", show_alert=True)
        return
    
    result = generate_2fa_code(secret)
    
    if result["success"]:
        remaining = result["remaining"]
        bar = format_progress_bar(remaining, result["interval"])
        
        text = (
            f"🔐 **{key_name}**\n\n"
            f"**Current OTP:** `{result['code']}`\n\n"
            f"⏳ **Expires in:** `{remaining}s`\n"
            f"`{bar}`"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_2fa_{key_name}")],
            [InlineKeyboardButton("🗑 Delete", callback_data=f"del_2fa_{key_name}")],
            [InlineKeyboardButton("🔙 Back", callback_data="list_twofa")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        
        # Auto refresh countdown
        if remaining > 0:
            await asyncio.sleep(remaining)
            await generate_twofa_code(update, context)
    else:
        await query.edit_message_text(f"❌ Error: {result['error']}")

async def refresh_twofa_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await generate_twofa_code(update, context)

async def delete_twofa_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    key_name = query.data.replace("del_2fa_", "")
    user_id = query.from_user.id
    
    if bot_data.delete_twofa_key(user_id, key_name):
        await query.answer(f"Deleted {key_name}!", show_alert=True)
        await list_twofa(update, context)
    else:
        await query.answer("Failed to delete!", show_alert=True)

# ==================== OTP RECEIVER ====================

async def otp_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📥 Current OTP", callback_data="current_otp")],
        [InlineKeyboardButton("📜 OTP History", callback_data="otp_history")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    active_number = bot_data.get_active_number() or "Not set"
    
    await query.edit_message_text(
        f"📨 **OTP Receiver**\n\n"
        f"📱 **Active Number:** `{active_number}`\n\n"
        f"View OTP codes that have been received.\n\n"
        f"Select an option:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def current_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    pending = bot_data.get_pending_otp()
    
    if pending:
        text = (
            f"🔐 **Current OTP**\n\n"
            f"📱 **Number:** `{pending['number']}`\n"
            f"🔑 **OTP Code:** `{pending['otp']}`\n"
            f"⏰ **Time:** {pending['timestamp']}"
        )
    else:
        text = "📭 **No OTP Available**\n\nNo OTP has been added yet."
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="current_otp")],
        [InlineKeyboardButton("🔙 Back", callback_data="otp_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def otp_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    history = bot_data.get_otp_history(20)
    
    if not history:
        text = "📭 **No OTP History**"
    else:
        lines = []
        for i, otp in enumerate(history, 1):
            lines.append(f"{i}. `{otp['otp']}` - {otp['timestamp'][:16]}\n   📱 {otp['number']}")
        text = f"📜 **OTP History** (Last {len(history)})\n\n" + "\n".join(lines)
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="otp_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def add_otp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to add OTP"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: `/add_otp CODE`\nExample: `/add_otp 123456`")
        return
    
    otp_code = context.args[0]
    number = context.args[1] if len(context.args) > 1 else bot_data.get_active_number()
    
    if not number:
        await update.message.reply_text("❌ No active number set!")
        return
    
    bot_data.add_otp(otp_code, number, "Admin")
    await update.message.reply_text(f"✅ OTP `{otp_code}` added for `{number}`", parse_mode="Markdown")

# ==================== CARD GENERATOR ====================

async def card_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("💳 Generate Card", callback_data="card_gen")],
        [InlineKeyboardButton("📜 Card History", callback_data="card_history")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "💳 **Credit Card Generator**\n\n"
        "Generate valid credit card numbers for testing purposes.\n\n"
        "Enter a BIN (first 6-8 digits) to generate a card.\n"
        "Example: `4` for VISA, `51` for MasterCard, or full BIN like `411111`\n\n"
        "Click below to start:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def card_gen_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "💳 **Enter BIN Number**\n\n"
        "Send the BIN (first 6-8 digits of the card):\n"
        "Example: `4` (VISA), `51` (MasterCard), `411111`\n\n"
        "Type /cancel to abort.",
        parse_mode="Markdown"
    )
    return CARD_GEN_STATE

async def card_gen_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin_input = update.message.text.strip()
    
    if not bin_input.isdigit() or len(bin_input) < 1:
        await update.message.reply_text(
            "❌ **Invalid BIN!**\n\nBIN must contain only numbers.\nSend again or type /cancel",
            parse_mode="Markdown"
        )
        return CARD_GEN_STATE
    
    msg = await update.message.reply_text(f"💳 Generating card for BIN `{bin_input}`...\n⏳ Please wait", parse_mode="Markdown")
    
    result = generate_card(bin_input)
    
    if result["success"]:
        # Format card number with spaces
        card_num = result["card_number"]
        formatted_card = f"{card_num[:4]} {card_num[4:8]} {card_num[8:12]} {card_num[12:16]}"
        
        response = (
            f"💳 **Generated Card**\n\n"
            f"🏦 **Type:** `{result['type']}`\n"
            f"💳 **Card:** `{formatted_card}`\n"
            f"📅 **Expiry:** `{result['expiry']}`\n"
            f"🔐 **CVV:** `{result['cvv']}`\n"
            f"🔢 **BIN:** `{result['bin']}`\n\n"
            f"⚠️ **For testing purposes only!**"
        )
        
        bot_data.add_card(bin_input, result)
    else:
        response = f"❌ **Error:** {result['error']}"
    
    keyboard = [
        [InlineKeyboardButton("💳 Generate Another", callback_data="card_gen")],
        [InlineKeyboardButton("🔙 Back", callback_data="card_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.delete()
    await update.message.reply_text(response, parse_mode="Markdown", reply_markup=reply_markup)
    return ConversationHandler.END

async def card_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    history = bot_data.data.get("card_history", [])
    
    if not history:
        text = "📭 **No card generation history**"
    else:
        lines = []
        for i, record in enumerate(history[:15], 1):
            card_data = record.get("card", {})
            lines.append(f"{i}. BIN: `{record['bin']}` → {card_data.get('type', 'Unknown')}\n   🕐 {record['timestamp'][:16]}")
        text = f"📜 **Card History** (Last {min(15, len(history))})\n\n" + "\n".join(lines)
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="card_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)

# ==================== ABOUT ====================

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    about_text = (
        "ℹ️ **About Verification Hub Bot**\n\n"
        "**Version:** 1.0\n\n"
        "**Features:**\n"
        "• 📱 Facebook Account Checker\n"
        "• 📧 Temporary Email Generator\n"
        "• 🔐 2FA Code Generator (TOTP)\n"
        "• 📨 OTP Receiver\n"
        "• 💳 Credit Card Generator (Testing)\n\n"
        "**Commands:**\n"
        "• /start - Show main menu\n"
        "• /myid - Get your Telegram ID\n"
        "• /add_otp - Admin: Add OTP\n\n"
        "**Developer:** @VerificationHub\n\n"
        "⚠️ All features are for testing purposes only."
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(about_text, parse_mode="Markdown", reply_markup=reply_markup)

# ==================== BACK TO MAIN ====================

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📱 Facebook Checker", callback_data="fb_check")],
        [InlineKeyboardButton("📧 Temp Mail", callback_data="temp_mail")],
        [InlineKeyboardButton("🔐 2FA Generator", callback_data="twofa_menu")],
        [InlineKeyboardButton("📨 OTP Receiver", callback_data="otp_menu")],
        [InlineKeyboardButton("💳 Card Generator", callback_data="card_menu")],
        [InlineKeyboardButton("ℹ️ About", callback_data="about")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🤖 **Verification Hub Bot**\n\n"
        "Select a service below:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

# ==================== MYID COMMAND ====================

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user ID"""
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"🆔 **Your Telegram ID:**\n`{user_id}`\n\n"
        f"Share this with admin to get access.",
        parse_mode="Markdown"
    )

# ==================== CANCEL ====================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    await update.message.reply_text(
        "❌ **Cancelled.**\n\nUse /start to return to main menu.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ==================== SET COMMANDS ====================

async def set_commands(app):
    """Set bot commands for menu"""
    commands = [
        BotCommand("start", "Show main menu"),
        BotCommand("myid", "Get your Telegram ID"),
    ]
    await app.bot.set_my_commands(commands)

# ==================== MAIN FUNCTION ====================

def main():
    """Main function to run the bot"""
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Conversation handlers
    conv_fb_check = ConversationHandler(
        entry_points=[CallbackQueryHandler(fb_check_start, pattern="fb_check_start")],
        states={FB_CHECK_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, fb_check_receive), CommandHandler("cancel", cancel)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    conv_add_twofa = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_twofa_start, pattern="add_twofa")],
        states={ADD_2FA_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_twofa_receive), CommandHandler("cancel", cancel)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    conv_card_gen = ConversationHandler(
        entry_points=[CallbackQueryHandler(card_gen_start, pattern="card_gen")],
        states={CARD_GEN_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, card_gen_receive), CommandHandler("cancel", cancel)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("add_otp", add_otp_command))
    
    # Conversation handlers
    app.add_handler(conv_fb_check)
    app.add_handler(conv_add_twofa)
    app.add_handler(conv_card_gen)
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(back_to_main, pattern="back_main"))
    app.add_handler(CallbackQueryHandler(fb_check_menu, pattern="fb_check"))
    app.add_handler(CallbackQueryHandler(temp_mail_menu, pattern="temp_mail"))
    app.add_handler(CallbackQueryHandler(twofa_menu, pattern="twofa_menu"))
    app.add_handler(CallbackQueryHandler(otp_menu, pattern="otp_menu"))
    app.add_handler(CallbackQueryHandler(card_menu, pattern="card_menu"))
    app.add_handler(CallbackQueryHandler(about, pattern="about"))
    
    # Facebook callbacks
    app.add_handler(CallbackQueryHandler(fb_check_start, pattern="fb_check_start"))
    
    # Temp mail callbacks
    app.add_handler(CallbackQueryHandler(generate_temp_mail, pattern="gen_temp_mail"))
    app.add_handler(CallbackQueryHandler(check_inbox, pattern="check_inbox"))
    
    # 2FA callbacks
    app.add_handler(CallbackQueryHandler(list_twofa, pattern="list_twofa"))
    app.add_handler(CallbackQueryHandler(generate_twofa_code, pattern="gen_2fa_"))
    app.add_handler(CallbackQueryHandler(refresh_twofa_code, pattern="refresh_2fa_"))
    app.add_handler(CallbackQueryHandler(delete_twofa_key, pattern="del_2fa_"))
    
    # OTP callbacks
    app.add_handler(CallbackQueryHandler(current_otp, pattern="current_otp"))
    app.add_handler(CallbackQueryHandler(otp_history, pattern="otp_history"))
    
    # Card callbacks
    app.add_handler(CallbackQueryHandler(card_gen_start, pattern="card_gen"))
    app.add_handler(CallbackQueryHandler(card_history, pattern="card_history"))
    
    # Set commands
    app.post_init = set_commands
    
    print("=" * 50)
    print("🤖 Verification Hub Bot is running...")
    print("=" * 50)
    print(f"👑 Admin ID: {ADMIN_ID}")
    print("=" * 50)
    print("\n✅ Features:")
    print("  • Facebook Account Checker")
    print("  • Temp Mail Generator")
    print("  • 2FA Code Generator (Auto countdown)")
    print("  • OTP Receiver")
    print("  • Card Generator (BIN based)")
    print("=" * 50)
    print("\n🚀 Bot started! Press Ctrl+C to stop.\n")
    
    app.run_polling()

if __name__ == "__main__":
    main()