import os
import logging
import asyncio
import threading
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from sqlmodel import Session
from backend.database import engine, Expense
from backend.parser import parse_expense_text

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_IDS = [
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip().isdigit()
]


def is_authorized(user_id: int, chat_id: int) -> bool:
    """Check if user/chat is authorized to use the bot."""
    if not ALLOWED_USER_IDS:
        # No whitelist configured = allow all
        return True
    return user_id in ALLOWED_USER_IDS or chat_id in ALLOWED_USER_IDS


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not update.message:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id

    if not is_authorized(user.id, chat_id):
        logger.warning(f"Unauthorized /start from user ID: {user.id}")
        return

    welcome = (
        "Family Budget Bot\n\n"
        "Send me expenses in natural language:\n"
        "• `coffee 25`\n"
        "• `groceries 340`\n"
        "• `150 fuel`\n"
        "• `wolt pizza 89`\n\n"
        "I'll auto-classify and log them!"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    if not update.message:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id

    if not is_authorized(user.id, chat_id):
        return

    help_text = (
        "*Quick Expense Logging*\n\n"
        "Just type the expense naturally:\n"
        "• `coffee 18` → Restaurants & Dining\n"
        "• `shufersal 250` → Groceries & Supermarket\n"
        "• `parking 30` → Transportation & Fuel\n\n"
        "*Supported Keywords:*\n"
        "Groceries: supermarket, groceries, shufersal, rami levy, mega\n"
        "Transport: fuel, gas, charging, parking, sonol, paz\n"
        "Dining: coffee, restaurant, wolt, cafe, pizza\n\n"
        "Unrecognized keywords go to 'General & Miscellaneous'.\n\n"
        "View dashboard at: http://localhost:8000"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages as expense entries."""
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id

    # Security check
    if not is_authorized(user.id, chat_id):
        logger.warning(f"Unauthorized message from user ID: {user.id}")
        return

    raw_text = update.message.text
    sender_name = user.first_name or "Family Member"

    # Parse the expense text
    amount, description, cat_id, cat_name = parse_expense_text(raw_text)

    if amount is None:
        await update.message.reply_text(
            "No amount found.\n\n"
            "Format examples:\n"
            "• `Groceries 340`\n"
            "• `Coffee 18`\n"
            "• `Gas 220`",
            parse_mode="Markdown"
        )
        return

    # Persist to database
    with Session(engine) as session:
        expense = Expense(
            amount=amount,
            description=description,
            category_id=cat_id,
            payer=sender_name,
            is_fixed=False
        )
        session.add(expense)
        session.commit()

    reply = (
        f"*Expense Logged*\n"
        f"Amount: {amount:,.2f}\n"
        f"Category: {cat_name}\n"
        f"Description: {description}\n"
        f"Logged By: {sender_name}"
    )
    await update.message.reply_text(reply, parse_mode="Markdown")


async def run_bot_async():
    """Run the Telegram bot with proper async handling."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set. Bot worker disabled.")
        return

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Telegram Bot starting long polling...")

    # Initialize the application
    await application.initialize()
    await application.start()

    # Start polling without blocking
    await application.updater.start_polling(drop_pending_updates=True)

    logger.info("Telegram Bot polling started successfully.")

    # Keep running until stopped
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("Bot polling cancelled, shutting down...")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def run_bot_in_thread():
    """
    Run the Telegram bot in a separate thread with its own event loop.
    This is necessary because FastAPI runs its own async loop.
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set. Bot worker disabled.")
        return None

    def bot_thread():
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(run_bot_async())
        except Exception as e:
            logger.error(f"Telegram bot error: {e}")
        finally:
            loop.close()

    thread = threading.Thread(target=bot_thread, daemon=True, name="TelegramBotThread")
    thread.start()
    logger.info("Telegram bot thread started.")
    return thread
