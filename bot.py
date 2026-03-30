import pyotp
import asyncio
import time
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, ContextTypes, filters
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

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")

user_keys = {}  # temporary memory
user_otp_messages = {}  # store active OTP messages

async def set_bot_commands(app):
    """Set bot commands for menu"""
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("myid", "Get your user ID"),
        BotCommand("help", "Show help message"),
        BotCommand("cancel", "Clear your saved key"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Bot commands set successfully")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 2FA Code Generator", callback_data="generate_2fa")],
        [InlineKeyboardButton("ℹ️ Help & Guide", callback_data="help_guide")]
    ])
    
    await update.message.reply_text(
        "⚡ **TOTP Generator Bot**\n\n"
        "Welcome to the TOTP OTP Generator Bot!\n\n"
        "🔑 **Features:**\n"
        "• Live OTP generation with countdown timer\n"
        "• Progress bar showing remaining time\n"
        "• Auto-delete expired OTPs\n"
        "• Refresh button for new codes\n\n"
        "Click the button below to get started!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "No username"
    first_name = update.effective_user.first_name or "No first name"
    
    await update.message.reply_text(
        f"📊 **Your User Information**\n\n"
        f"🆔 **User ID:** `{user_id}`\n"
        f"👤 **Username:** @{username}\n"
        f"📛 **First Name:** {first_name}\n\n"
        f"ℹ️ Share this ID if needed for support.",
        parse_mode="Markdown"
    )

async def generate_2fa_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt user to send their 2FA key"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
    ])
    
    await query.message.edit_text(
        "🔐 **2FA Code Generator**\n\n"
        "Please send me your TOTP secret key to start generating codes.\n\n"
        "**How to get your secret key:**\n"
        "1. Open your 2FA app (Google Authenticator, Authy, etc.)\n"
        "2. Look for the secret key or setup key\n"
        "3. Copy and paste it here\n\n"
        "**Example:** `JBSWY3DPEHPK3PXP`\n\n"
        "⚠️ **Note:** Your key will be stored temporarily and cleared when bot restarts.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def help_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help guide"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 Generate 2FA Code", callback_data="generate_2fa")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
    ])
    
    help_text = (
        "📖 **TOTP Bot Help Guide**\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/myid - Get your user ID\n"
        "/help - Show this help message\n"
        "/cancel - Clear your saved key\n\n"
        "**How to use 2FA Generator:**\n"
        "1️⃣ Click '2FA Code Generator' button\n"
        "2️⃣ Send your TOTP secret key\n"
        "3️⃣ Watch live OTP with countdown timer\n"
        "4️⃣ Click 'Refresh' for new code after expiry\n\n"
        "**What is TOTP?**\n"
        "Time-based One-Time Password (TOTP) generates temporary codes that expire every 30 seconds for secure 2-factor authentication.\n\n"
        "**Security Note:**\n"
        "Keys are stored temporarily and never saved permanently. All data is cleared when the bot restarts."
    )
    
    await query.message.edit_text(help_text, parse_mode="Markdown", reply_markup=keyboard)

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to main menu"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 2FA Code Generator", callback_data="generate_2fa")],
        [InlineKeyboardButton("ℹ️ Help & Guide", callback_data="help_guide")]
    ])
    
    await query.message.edit_text(
        "⚡ **TOTP Generator Bot**\n\n"
        "Welcome to the TOTP OTP Generator Bot!\n\n"
        "🔑 **Features:**\n"
        "• Live OTP generation with countdown timer\n"
        "• Progress bar showing remaining time\n"
        "• Auto-delete expired OTPs\n"
        "• Refresh button for new codes\n\n"
        "Click the button below to get started!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE, secret):
    """Generate and display OTP with live countdown"""
    user_id = update.effective_user.id
    
    # Validate secret first
    try:
        totp = pyotp.TOTP(secret)
        test_otp = totp.now()
        if not test_otp or len(test_otp) != 6:
            raise ValueError("Invalid OTP generated")
    except Exception as e:
        error_msg = await update.effective_message.reply_text(
            "❌ **Invalid Secret Key!**\n\n"
            "Please send a valid TOTP secret key.\n"
            f"Error: {str(e)}",
            parse_mode="Markdown"
        )
        await asyncio.sleep(5)
        try:
            await error_msg.delete()
        except:
            pass
        return

    # Store key for refresh
    user_keys[user_id] = secret

    # Send initial message
    msg = await update.effective_message.reply_text("⏳ Generating OTP...")
    
    # Store message ID for cleanup
    if user_id not in user_otp_messages:
        user_otp_messages[user_id] = []
    user_otp_messages[user_id].append(msg.message_id)

    # Countdown loop
    while True:
        current_time = int(time.time())
        remaining = totp.interval - (current_time % totp.interval)
        
        # Get current OTP
        otp = totp.at(current_time)
        
        # Create progress bar
        progress = int((totp.interval - remaining) / totp.interval * 20)
        bar = "█" * progress + "░" * (20 - progress)
        
        # Determine emoji based on remaining time
        if remaining > 20:
            time_emoji = "🟢"
        elif remaining > 10:
            time_emoji = "🟡"
        else:
            time_emoji = "🔴"
        
        text = (
            f"🔐 **Current OTP:**\n"
            f"```\n{otp}\n```\n\n"
            f"⏳ **Expires in:** `{remaining}s` {time_emoji}\n"
            f"`{bar}`\n\n"
            f"🔄 Click the button below when expired"
        )
        
        try:
            await msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            pass

        if remaining <= 1:
            break

        await asyncio.sleep(0.5)  # Update twice per second for smoother countdown

    # Delete expired message
    try:
        await msg.delete()
        if user_id in user_otp_messages:
            user_otp_messages[user_id].remove(msg.message_id)
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

    # Show refresh button
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Generate New OTP", callback_data="refresh_otp")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ])

    refresh_msg = await update.effective_message.reply_text(
        "⌛ **OTP Expired!**\n\nClick below to generate a new code.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    
    if user_id not in user_otp_messages:
        user_otp_messages[user_id] = []
    user_otp_messages[user_id].append(refresh_msg.message_id)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (TOTP secrets)"""
    secret = update.message.text.strip().upper().replace(" ", "")
    
    # Validate secret format (basic check)
    if len(secret) < 16 or len(secret) > 32:
        await update.message.reply_text(
            "❌ **Invalid Key!**\n\n"
            "TOTP secret should be 16-32 characters long.\n"
            "Example: `JBSWY3DPEHPK3PXP`\n\n"
            "Please check your key and try again.",
            parse_mode="Markdown"
        )
        return
    
    # Clean up old messages for this user
    if update.effective_user.id in user_otp_messages:
        for msg_id in user_otp_messages[update.effective_user.id]:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=msg_id
                )
            except:
                pass
        user_otp_messages[update.effective_user.id] = []
    
    try:
        # Test if valid
        totp = pyotp.TOTP(secret)
        test_otp = totp.now()
        if not test_otp or len(test_otp) != 6:
            raise ValueError("Invalid OTP format")
        
        await generate(update, context, secret)
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Invalid TOTP Key!**\n\n"
            f"Error: {str(e)}\n\n"
            f"Please send a valid base32 encoded secret.\n"
            f"Example: `JBSWY3DPEHPK3PXP`",
            parse_mode="Markdown"
        )

async def refresh_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refresh OTP button handler"""
    query = update.callback_query
    await query.answer("Generating new OTP...")
    
    user_id = query.from_user.id

    if user_id not in user_keys:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 Send 2FA Key", callback_data="generate_2fa")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
        ])
        await query.message.edit_text(
            "❌ **No Key Found!**\n\n"
            "Please send your TOTP secret key first.\n\n"
            "Click below to get started.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    secret = user_keys[user_id]
    
    # Delete old expired message
    try:
        await query.message.delete()
    except:
        pass
    
    # Create new update object for generate function
    class FakeUpdate:
        effective_user = query.from_user
        effective_message = query.message
        effective_chat = query.message.chat
    
    await generate(FakeUpdate(), context, secret)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear saved key"""
    user_id = update.effective_user.id
    
    # Clean up messages
    if user_id in user_otp_messages:
        for msg_id in user_otp_messages[user_id]:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=msg_id
                )
            except:
                pass
        del user_otp_messages[user_id]
    
    if user_id in user_keys:
        del user_keys[user_id]
        await update.message.reply_text(
            "✅ **Cleared Your Saved Key!**\n\n"
            "Send a new key to start over or use /start for main menu.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "ℹ️ **No Active Key Found**\n\n"
            "Send a TOTP secret to get started.",
            parse_mode="Markdown"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 Generate 2FA Code", callback_data="generate_2fa")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ])
    
    help_text = (
        "📖 **TOTP Bot Help**\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/myid - Get your user ID\n"
        "/help - Show this help message\n"
        "/cancel - Clear your saved key\n\n"
        "**How to use:**\n"
        "1. Get your TOTP secret key from any 2FA app\n"
        "2. Send the key to this bot\n"
        "3. Watch live OTP codes with countdown\n"
        "4. Click refresh button for new OTP\n\n"
        "**Note:** Keys are stored temporarily and cleared when bot restarts."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=keyboard)

def main():
    """Main function to run the bot"""
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(generate_2fa_prompt, pattern="generate_2fa"))
    app.add_handler(CallbackQueryHandler(help_guide, pattern="help_guide"))
    app.add_handler(CallbackQueryHandler(back_to_main_menu, pattern="main_menu"))
    app.add_handler(CallbackQueryHandler(refresh_otp, pattern="refresh_otp"))
    
    # Set bot commands
    app.post_init = set_bot_commands
    
    print("🤖 TOTP Bot is running...")
    print("Features:")
    print("✓ Menu buttons in left sidebar (Start, MyID)")
    print("✓ 2FA Code Generator with live countdown")
    print("✓ Progress bar showing remaining time")
    print("✓ Auto-delete expired OTPs")
    print("✓ Refresh button for new codes")
    print("Press Ctrl+C to stop")
    
    app.run_polling()

if __name__ == "__main__":
    main()
