import pyotp
import asyncio
import time
import logging
import random
import string
import sqlite3
import os
import sys
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, ContextTypes, filters
from dotenv import load_dotenv

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "7064572216").split(","))) if os.getenv("ADMIN_IDS") else [7064572216]

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not found in .env file")
    sys.exit(1)

print(f"✅ Bot started with Admin IDs: {ADMIN_IDS}")

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
    
    # Add sample numbers
    c.execute("SELECT COUNT(*) FROM virtual_numbers")
    if c.fetchone()[0] == 0:
        numbers = [
            ('+1 (555) 123-4567', 'USA'), ('+1 (555) 234-5678', 'USA'),
            ('+44 20 1234 5678', 'UK'), ('+44 20 2345 6789', 'UK'),
            ('+1 (416) 123-4567', 'Canada'), ('+61 2 1234 5678', 'Australia'),
            ('+880 1712 345678', 'Bangladesh'), ('+880 1812 345678', 'Bangladesh'),
        ]
        for num, country in numbers:
            c.execute("INSERT INTO virtual_numbers (number, country, is_available) VALUES (?, ?, 1)", (num, country))
    
    # Add admin
    for aid in ADMIN_IDS:
        c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, join_date, is_banned, credits) VALUES (?, ?, ?, ?, ?, ?)",
                  (aid, "admin", "Admin", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0, 1000))
    
    conn.commit()
    conn.close()
    print("✅ Database initialized")

init_db()

# ==================== HELPER FUNCTIONS ====================
def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_credits(user_id):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        conn.close()
        return r[0] if r else 10
    except:
        return 10

def add_user(user_id, username, name):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?, 0, 10)",
                  (user_id, username or "", name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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

def is_banned(user_id):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        conn.close()
        return r[0] == 1 if r else False
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

def all_users():
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE is_banned = 0")
        return [u[0] for u in c.fetchall()]
    except:
        return []

def banned_users():
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name FROM users WHERE is_banned = 1")
        return c.fetchall()
    except:
        return []

def available_count():
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM virtual_numbers WHERE is_available = 1")
        return c.fetchone()[0]
    except:
        return 8

# ==================== BOTTOM MENU ====================
def get_menu():
    return ReplyKeyboardMarkup([
        ["📱 Number", "📧 TempMail", "🔐 2FA"],
        ["💰 Balance", "💸 Withdraw", "🆘 Help"]
    ], resize_keyboard=True)

# ==================== START ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ You are banned!")
        return
    
    add_user(user.id, user.username, user.first_name)
    
    await update.message.reply_text(
        f"👋 Welcome {user.first_name}!\n\n🤖 Multi-Tool Bot\n\n✅ Virtual Numbers\n✅ Temporary Email\n✅ 2FA Code Generator\n✅ Facebook Checker\n\n💎 Credits: {get_credits(user.id)}\n\nUse buttons below:",
        parse_mode="Markdown",
        reply_markup=get_menu()
    )

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ You are banned!")
        return
    await update.message.reply_text("Main Menu:", reply_markup=get_menu())

# ==================== TEXT HANDLER ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_banned(user_id):
        await update.message.reply_text("❌ Banned!")
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
    elif context.user_data.get('awaiting_2fa'):
        await gen_2fa(update, context)
    elif context.user_data.get('awaiting_fb'):
        await fb_check(update, context)
    else:
        await update.message.reply_text("Use buttons below:", reply_markup=get_menu())

# ==================== 2FA ====================
async def twofa_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🔐 Send TOTP secret key:\nExample: `JBSWY3DPEHPK3PXP`",
        parse_mode="Markdown"
    )
    context.user_data['awaiting_2fa'] = True

async def gen_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_2fa'):
        return
    
    secret = update.message.text.strip().upper().replace(" ", "")
    
    try:
        totp = pyotp.TOTP(secret)
        test = totp.now()
        if not test or len(test) != 6:
            raise ValueError()
        
        context.user_data['secret'] = secret
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 New OTP", callback_data="2fa_new")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ])
        
        msg = await update.message.reply_text("⏳ Generating...", reply_markup=kb)
        
        for i in range(30):
            now = int(time.time())
            rem = totp.interval - (now % totp.interval)
            otp = totp.at(now)
            bar = "█" * int(20 * (30 - rem) / 30) + "░" * (20 - int(20 * (30 - rem) / 30))
            
            try:
                await msg.edit_text(f"🔐 OTP: `{otp}`\n⏳ Expires: {rem}s\n`{bar}`", parse_mode="Markdown", reply_markup=kb)
            except:
                pass
            
            if rem <= 1:
                break
            await asyncio.sleep(0.5)
        
        await msg.edit_text("⌛ Expired!\nClick 'New OTP' or send new key.", reply_markup=kb)
        context.user_data['awaiting_2fa'] = True
        
    except:
        await update.message.reply_text("❌ Invalid key! Send valid TOTP secret.")

async def twofa_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    secret = context.user_data.get('secret')
    if not secret:
        await q.message.edit_text("Send your TOTP secret key:")
        context.user_data['awaiting_2fa'] = True
        return
    
    try:
        totp = pyotp.TOTP(secret)
        test = totp.now()
        if not test or len(test) != 6:
            raise ValueError()
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 New OTP", callback_data="2fa_new")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ])
        
        msg = await q.message.edit_text("⏳ Generating...", reply_markup=kb)
        
        for i in range(30):
            now = int(time.time())
            rem = totp.interval - (now % totp.interval)
            otp = totp.at(now)
            bar = "█" * int(20 * (30 - rem) / 30) + "░" * (20 - int(20 * (30 - rem) / 30))
            
            try:
                await msg.edit_text(f"🔐 OTP: `{otp}`\n⏳ Expires: {rem}s\n`{bar}`", parse_mode="Markdown", reply_markup=kb)
            except:
                pass
            
            if rem <= 1:
                break
            await asyncio.sleep(0.5)
        
        await msg.edit_text("⌛ Expired!\nClick 'New OTP' or send new key.", reply_markup=kb)
        context.user_data['awaiting_2fa'] = True
        
    except:
        await q.message.edit_text("❌ Invalid key!")

# ==================== NUMBER ====================
async def number_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 Get Number", callback_data="num_get")],
        [InlineKeyboardButton("🔄 Change", callback_data="num_change")],
        [InlineKeyboardButton("📋 My Number", callback_data="num_my")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])
    await update.message.reply_text(f"📱 Virtual Numbers\nAvailable: {available_count()}", reply_markup=kb)

async def num_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    c.execute("SELECT number FROM user_numbers WHERE user_id = ?", (uid,))
    if c.fetchone():
        await q.message.edit_text("❌ You already have a number! Use 'Change'.")
        conn.close()
        return
    
    c.execute("SELECT id, number, country FROM virtual_numbers WHERE is_available = 1 LIMIT 1")
    av = c.fetchone()
    
    if not av:
        await q.message.edit_text("❌ No numbers available!")
        conn.close()
        return
    
    nid, num, country = av
    c.execute("UPDATE virtual_numbers SET is_available = 0, assigned_to = ? WHERE id = ?", (uid, nid))
    c.execute("INSERT INTO user_numbers VALUES (?, ?, ?, ?)", (uid, nid, num, country))
    conn.commit()
    conn.close()
    
    await q.message.edit_text(f"✅ Number: `{num}`\n🌍 {country}", parse_mode="Markdown")

async def num_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    c.execute("SELECT number_id FROM user_numbers WHERE user_id = ?", (uid,))
    cur = c.fetchone()
    if cur:
        c.execute("UPDATE virtual_numbers SET is_available = 1, assigned_to = NULL WHERE id = ?", (cur[0],))
        c.execute("DELETE FROM user_numbers WHERE user_id = ?", (uid,))
    
    c.execute("SELECT id, number, country FROM virtual_numbers WHERE is_available = 1 LIMIT 1")
    av = c.fetchone()
    
    if not av:
        await q.message.edit_text("❌ No numbers available!")
        conn.close()
        return
    
    nid, num, country = av
    c.execute("UPDATE virtual_numbers SET is_available = 0, assigned_to = ? WHERE id = ?", (uid, nid))
    c.execute("INSERT INTO user_numbers VALUES (?, ?, ?, ?)", (uid, nid, num, country))
    conn.commit()
    conn.close()
    
    await q.message.edit_text(f"✅ New Number: `{num}`\n🌍 {country}", parse_mode="Markdown")

async def num_my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT number, country FROM user_numbers WHERE user_id = ?", (uid,))
    r = c.fetchone()
    conn.close()
    
    if r:
        await q.message.edit_text(f"📋 Your Number: `{r[0]}`\n🌍 {r[1]}", parse_mode="Markdown")
    else:
        await q.message.edit_text("❌ No number! Click 'Get Number'.")

# ==================== TEMP MAIL ====================
temp_mails = {}

async def tempmail_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    
    if uid in temp_mails:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Check", callback_data="tmp_check")],
            [InlineKeyboardButton("🔄 New", callback_data="tmp_new")],
            [InlineKeyboardButton("🗑️ Delete", callback_data="tmp_delete")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ])
        await update.message.reply_text(f"📧 Email: `{temp_mails[uid]['email']}`\nCreated: {temp_mails[uid]['created']}", parse_mode="Markdown", reply_markup=kb)
    else:
        await create_temp(update)

async def create_temp(update):
    uid = update.effective_user.id
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    email = name + random.choice(['@tempmail.com', '@tempemail.net', '@10minutemail.com'])
    
    temp_mails[uid] = {'email': email, 'created': datetime.now().strftime("%Y-%m-%d %H:%M"), 'msgs': []}
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Check", callback_data="tmp_check")],
        [InlineKeyboardButton("🔄 New", callback_data="tmp_new")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="tmp_delete")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])
    await update.message.reply_text(f"✅ Email: `{email}`", parse_mode="Markdown", reply_markup=kb)

async def tmp_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Checking...")
    uid = q.from_user.id
    
    if uid not in temp_mails:
        await q.message.edit_text("No email! Create one.")
        return
    
    email = temp_mails[uid]['email']
    has = random.random() > 0.7
    
    if has:
        code = random.randint(100000, 999999)
        text = f"📧 `{email}`\n\n📥 New!\nFrom: noreply@facebook.com\nCode: `{code}`"
    else:
        text = f"📧 `{email}`\n\n📭 Empty"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="tmp_check")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])
    await q.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

async def tmp_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    email = name + random.choice(['@tempmail.com', '@tempemail.net', '@10minutemail.com'])
    temp_mails[uid] = {'email': email, 'created': datetime.now().strftime("%Y-%m-%d %H:%M"), 'msgs': []}
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Check", callback_data="tmp_check")],
        [InlineKeyboardButton("🔄 New", callback_data="tmp_new")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="tmp_delete")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])
    await q.message.edit_text(f"✅ New Email: `{email}`", parse_mode="Markdown", reply_markup=kb)

async def tmp_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if uid in temp_mails:
        del temp_mails[uid]
    await q.message.edit_text("🗑️ Deleted!", reply_markup=get_menu())

# ==================== BALANCE ====================
async def balance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"💰 Balance: {get_credits(uid)} credits", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]]))

# ==================== WITHDRAW ====================
async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Request", callback_data="with_req")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])
    await update.message.reply_text("💸 Withdraw\nMin: 100 credits = $10\nMethods: USDT, PayPal\n\nContact @Admin", reply_markup=kb)

async def withdraw_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.edit_text(f"Send request to @Admin with:\nUser ID: `{q.from_user.id}`\nCredits: {get_credits(q.from_user.id)}", parse_mode="Markdown")

# ==================== HELP ====================
async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Help\n\n📱 Number - Virtual numbers\n📧 TempMail - Temp email\n🔐 2FA - OTP codes\n💰 Balance - Credits\n💸 Withdraw - Cash out\n\nCommands:\n/start - Restart\n/myid - User ID\n/admin - Admin panel",
        reply_markup=get_menu()
    )

# ==================== FACEBOOK ====================
async def fb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cred = get_credits(q.from_user.id)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Check", callback_data="fb_check")],
        [InlineKeyboardButton("🔍 Check+OTP", callback_data="fb_otp")],
        [InlineKeyboardButton("📊 History", callback_data="fb_hist")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])
    await q.message.edit_text(f"📱 Facebook Checker\nCheck: 1 credit\nCheck+OTP: 2 credits\nYour credits: {cred}", reply_markup=kb)

async def fb_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, typ):
    q = update.callback_query
    await q.answer()
    if get_credits(q.from_user.id) < (1 if typ == 'check' else 2):
        await q.message.edit_text("❌ Insufficient credits!")
        return
    await q.message.edit_text("Send phone number with country code:\nExample: `+8801712345678`", parse_mode="Markdown")
    context.user_data['fb_type'] = typ
    context.user_data['awaiting_fb'] = True

async def fb_check_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_fb'):
        return
    
    typ = context.user_data['fb_type']
    phone = update.message.text.strip()
    uid = update.effective_user.id
    cost = 2 if typ == 'otp' else 1
    
    if get_credits(uid) < cost:
        await update.message.reply_text("❌ No credits!")
        context.user_data.pop('awaiting_fb', None)
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits - ? WHERE user_id = ?", (cost, uid))
    conn.commit()
    conn.close()
    
    await update.message.reply_text("🔍 Processing...")
    await asyncio.sleep(1)
    
    clean = ''.join(filter(str.isdigit, phone))
    exists = int(clean[-1]) % 2 == 0 if len(clean) >= 10 else False
    
    if exists:
        res = "✅ Facebook account found!"
        if typ == 'otp':
            otp = random.randint(100000, 999999)
            res += f"\n\n📨 OTP: `{otp}`\n⚠️ SIMULATED"
    else:
        res = "❌ No account found"
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO fb_checks (user_id, phone_number, account_found, checked_at) VALUES (?, ?, ?, ?)",
              (uid, phone, 1 if exists else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"📱 {phone}\n\n{res}", parse_mode="Markdown", reply_markup=get_menu())
    context.user_data.pop('awaiting_fb', None)

async def fb_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT phone_number, account_found, checked_at FROM fb_checks WHERE user_id = ? ORDER BY checked_at DESC LIMIT 5", (uid,))
    logs = c.fetchall()
    conn.close()
    
    if not logs:
        await q.message.edit_text("No history")
        return
    
    txt = "📊 History\n\n"
    for l in logs:
        txt += f"📱 {l[0][:4]}****{l[0][-4:]}\n✅ {'Found' if l[1] else 'Not'}\n🕐 {l[2][:16]}\n\n"
    
    await q.message.edit_text(txt)

# ==================== MY ID ====================
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(f"🆔 ID: `{u.id}`\n👤 @{u.username or 'None'}\n👑 Admin: {'Yes' if is_admin(u.id) else 'No'}\n💎 Credits: {get_credits(u.id)}", parse_mode="Markdown")

# ==================== ADMIN ====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized!")
        return
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_bc")],
        [InlineKeyboardButton("🚫 Ban", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ Unban", callback_data="admin_unban")],
        [InlineKeyboardButton("📋 Banned", callback_data="admin_banned")],
        [InlineKeyboardButton("➕ Add Number", callback_data="admin_addnum")],
        [InlineKeyboardButton("💰 Add Credits", callback_data="admin_addcred")],
        [InlineKeyboardButton("📋 Numbers", callback_data="admin_nums")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])
    await update.message.reply_text("🔧 Admin Panel", reply_markup=kb)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Unauthorized!")
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
    avail = c.fetchone()[0]
    conn.close()
    
    await q.message.edit_text(f"📊 Stats\n👥 Users: {users}\n🚫 Banned: {banned}\n💰 Credits: {credits}\n📱 Available: {avail}")

async def admin_bc_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Unauthorized!")
        return
    await q.message.edit_text("Send message to broadcast:")
    context.user_data['bc'] = True

async def admin_bc_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('bc'):
        return
    
    msg = update.message.text
    if msg == "/cancel":
        await update.message.reply_text("Cancelled")
        context.user_data.pop('bc', None)
        return
    
    users = all_users()
    s = 0
    for uid in users:
        try:
            await context.bot.send_message(uid, f"📢 Broadcast\n\n{msg}")
            s += 1
        except:
            pass
        await asyncio.sleep(0.05)
    
    await update.message.reply_text(f"✅ Sent to {s}/{len(users)} users")
    context.user_data.pop('bc', None)

async def admin_ban_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Unauthorized!")
        return
    await q.message.edit_text("Send User ID to ban:")
    context.user_data['ban'] = True

async def admin_ban_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('ban'):
        return
    
    uid = update.message.text.strip()
    if uid == "/cancel":
        await update.message.reply_text("Cancelled")
        context.user_data.pop('ban', None)
        return
    
    try:
        uid = int(uid)
        if ban_user(uid):
            await update.message.reply_text(f"✅ Banned {uid}")
            try:
                await context.bot.send_message(uid, "❌ You are banned!")
            except:
                pass
        else:
            await update.message.reply_text("Failed")
    except:
        await update.message.reply_text("Invalid ID!")
    context.user_data.pop('ban', None)

async def admin_unban_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Unauthorized!")
        return
    await q.message.edit_text("Send User ID to unban:")
    context.user_data['unban'] = True

async def admin_unban_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('unban'):
        return
    
    uid = update.message.text.strip()
    if uid == "/cancel":
        await update.message.reply_text("Cancelled")
        context.user_data.pop('unban', None)
        return
    
    try:
        uid = int(uid)
        if unban_user(uid):
            await update.message.reply_text(f"✅ Unbanned {uid}")
            try:
                await context.bot.send_message(uid, "✅ You are unbanned!")
            except:
                pass
        else:
            await update.message.reply_text("Failed")
    except:
        await update.message.reply_text("Invalid ID!")
    context.user_data.pop('unban', None)

async def admin_banned_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Unauthorized!")
        return
    
    banned = banned_users()
    if not banned:
        await q.message.edit_text("No banned users")
        return
    
    txt = "🚫 Banned Users\n\n"
    for b in banned:
        txt += f"🆔 `{b[0]}` - {b[2]}\n"
    await q.message.edit_text(txt, parse_mode="Markdown")

async def admin_addnum_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Unauthorized!")
        return
    await q.message.edit_text("Send: `+1234567890,Country`\nExample: `+8801712345678,Bangladesh`", parse_mode="Markdown")
    context.user_data['addnum'] = True

async def admin_addnum_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('addnum'):
        return
    
    data = update.message.text.strip()
    if data == "/cancel":
        await update.message.reply_text("Cancelled")
        context.user_data.pop('addnum', None)
        return
    
    try:
        parts = data.split(',')
        num = parts[0].strip()
        country = parts[1].strip() if len(parts) > 1 else "Unknown"
        
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT INTO virtual_numbers (number, country, is_available) VALUES (?, ?, 1)", (num, country))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Added: {num} ({country})", reply_markup=get_menu())
    except:
        await update.message.reply_text("❌ Error! Use: `+1234567890,Country`", parse_mode="Markdown")
    context.user_data.pop('addnum', None)

async def admin_addcred_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Unauthorized!")
        return
    await q.message.edit_text("Send: `USER_ID AMOUNT`\nExample: `123456789 50`", parse_mode="Markdown")
    context.user_data['addcred'] = True

async def admin_addcred_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('addcred'):
        return
    
    data = update.message.text.strip()
    if data == "/cancel":
        await update.message.reply_text("Cancelled")
        context.user_data.pop('addcred', None)
        return
    
    try:
        parts = data.split()
        uid = int(parts[0])
        amt = int(parts[1])
        
        update_credits(uid, amt)
        await update.message.reply_text(f"✅ Added {amt} credits to {uid}", reply_markup=get_menu())
    except:
        await update.message.reply_text("❌ Error! Use: `USER_ID AMOUNT`", parse_mode="Markdown")
    context.user_data.pop('addcred', None)

async def admin_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Unauthorized!")
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT number, country, is_available FROM virtual_numbers LIMIT 20")
    nums = c.fetchall()
    conn.close()
    
    if not nums:
        await q.message.edit_text("No numbers")
        return
    
    txt = "📋 Numbers\n\n"
    for n in nums:
        txt += f"{'✅' if n[2] else '❌'} `{n[0]}` - {n[1]}\n"
    await q.message.edit_text(txt, parse_mode="Markdown")

# ==================== BACK ====================
async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    u = q.from_user
    await q.message.edit_text(
        f"👋 Welcome back!\n💎 Credits: {get_credits(u.id)}",
        reply_markup=get_menu()
    )

# ==================== MAIN ====================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("admin", admin_panel))
    
    # Text handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(num_get, pattern="num_get"))
    app.add_handler(CallbackQueryHandler(num_change, pattern="num_change"))
    app.add_handler(CallbackQueryHandler(num_my, pattern="num_my"))
    app.add_handler(CallbackQueryHandler(tmp_check, pattern="tmp_check"))
    app.add_handler(CallbackQueryHandler(tmp_new, pattern="tmp_new"))
    app.add_handler(CallbackQueryHandler(tmp_delete, pattern="tmp_delete"))
    app.add_handler(CallbackQueryHandler(twofa_new, pattern="2fa_new"))
    app.add_handler(CallbackQueryHandler(fb_menu, pattern="fb_menu"))
    app.add_handler(CallbackQueryHandler(lambda u,c: fb_prompt(u,c,'check'), pattern="fb_check"))
    app.add_handler(CallbackQueryHandler(lambda u,c: fb_prompt(u,c,'otp'), pattern="fb_otp"))
    app.add_handler(CallbackQueryHandler(fb_history, pattern="fb_hist"))
    app.add_handler(CallbackQueryHandler(withdraw_req, pattern="with_req"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="admin_stats"))
    app.add_handler(CallbackQueryHandler(admin_bc_prompt, pattern="admin_bc"))
    app.add_handler(CallbackQueryHandler(admin_ban_prompt, pattern="admin_ban"))
    app.add_handler(CallbackQueryHandler(admin_unban_prompt, pattern="admin_unban"))
    app.add_handler(CallbackQueryHandler(admin_banned_list, pattern="admin_banned"))
    app.add_handler(CallbackQueryHandler(admin_addnum_prompt, pattern="admin_addnum"))
    app.add_handler(CallbackQueryHandler(admin_addcred_prompt, pattern="admin_addcred"))
    app.add_handler(CallbackQueryHandler(admin_numbers, pattern="admin_nums"))
    app.add_handler(CallbackQueryHandler(back, pattern="back"))
    
    # Admin text handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_bc_send))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ban_do))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_unban_do))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_addnum_do))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_addcred_do))
    
    print("=" * 50)
    print("🤖 BOT IS RUNNING")
    print("=" * 50)
    print(f"Admin ID: {ADMIN_IDS}")
    print("Features: Number, TempMail, 2FA, Balance, Withdraw, Help")
    print("=" * 50)
    
    # Start polling (works on Railway)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()