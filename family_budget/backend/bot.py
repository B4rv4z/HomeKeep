import os
import logging
import asyncio
import threading
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters
from sqlmodel import Session
from backend.database import engine, Expense
from backend.parser import parse_expense_text, parse_bulk_transactions

logger = logging.getLogger(__name__)

# In-memory storage for pending bulk imports (keyed by unique ID)
# Format: {import_id: {"transactions": [...], "sender_name": str, "chat_id": int}}
pending_imports = {}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
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
        "*Bulk Import:*\n"
        "• `/bulk` followed by multiple lines\n"
        "• Or upload a file (PDF, TXT, CSV, XLSX)\n\n"
        "*Supported Keywords:*\n"
        "Groceries: supermarket, groceries, shufersal, rami levy, mega\n"
        "Transport: fuel, gas, charging, parking, sonol, paz\n"
        "Dining: coffee, restaurant, wolt, cafe, pizza\n\n"
        "Unrecognized keywords go to 'General & Miscellaneous'.\n\n"
        "View dashboard at: http://localhost:8000"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def bulk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /bulk command - parse multi-line transactions."""
    if not update.message:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id

    if not is_authorized(user.id, chat_id):
        return

    # Get text after the /bulk command
    raw_text = update.message.text
    if " " in raw_text:
        bulk_text = raw_text.split(" ", 1)[1]
    else:
        await update.message.reply_text(
            "*Bulk Import*\n\n"
            "Paste your CC transactions after the command:\n"
            "`/bulk\n"
            "Shufersal 150.00\n"
            "Wolt 89.50\n"
            "Paz Gas 220.00`\n\n"
            "Or upload a file (PDF, TXT, CSV, XLSX) with your statement.",
            parse_mode="Markdown"
        )
        return

    await process_bulk_text(update, bulk_text, user.first_name or "Family Member")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads (PDF, TXT, CSV) for bulk transaction import."""
    if not update.message or not update.message.document:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id

    if not is_authorized(user.id, chat_id):
        logger.warning(f"Unauthorized document from user ID: {user.id}")
        return

    document = update.message.document
    file_name = document.file_name or "unknown"
    file_size = document.file_size or 0

    # Limit file size (1MB max)
    if file_size > 1024 * 1024:
        await update.message.reply_text("File too large. Maximum size is 1MB.")
        return

    # Check file type
    allowed_extensions = [".txt", ".csv", ".pdf", ".xlsx", ".xls"]
    file_ext = "." + file_name.split(".")[-1].lower() if "." in file_name else ""

    if file_ext not in allowed_extensions:
        await update.message.reply_text(
            f"Unsupported file type: {file_ext}\n"
            f"Supported formats: TXT, CSV, PDF, XLSX"
        )
        return

    await update.message.reply_text(f"Processing {file_name}...")

    try:
        # Download file
        file = await document.get_file()
        file_bytes = await file.download_as_bytearray()

        # Extract text based on file type
        if file_ext == ".pdf":
            text = extract_text_from_pdf(file_bytes)
        elif file_ext in [".xlsx", ".xls"]:
            text = extract_text_from_xlsx(file_bytes)
        else:
            # TXT or CSV - decode as text
            text = file_bytes.decode("utf-8", errors="ignore")

        if not text.strip():
            await update.message.reply_text("Could not extract text from the file.")
            return

        # Extract expected total for validation
        expected_total = 0.0
        if file_ext == ".pdf":
            expected_total = extract_expected_total_from_pdf(bytes(file_bytes))
        elif file_ext in [".xlsx", ".xls"]:
            expected_total = extract_expected_total_from_xlsx(bytes(file_bytes))

        logger.info(f"Expected total from file: {expected_total}")
        await process_bulk_text(update, text, user.first_name or "Family Member", expected_total)

    except Exception as e:
        logger.error(f"Document processing error: {e}")
        await update.message.reply_text(f"Error processing file: {str(e)}")


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes. Falls back to empty if PyMuPDF not installed."""
    try:
        import pymupdf
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    except ImportError:
        # Try legacy import for older versions
        try:
            import fitz
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text
        except ImportError:
            logger.warning("PyMuPDF not installed - PDF parsing unavailable")
            return ""
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        return ""


def extract_expected_total_from_xlsx(xlsx_bytes: bytes) -> float:
    """
    Extract the expected total from an XLSX CC statement.
    Looks for patterns like:
    - MAX: Footer rows with "סך הכל" followed by amount
    - CAL: Header with "עסקאות לחיוב ב-XX/XX/XXXX: X,XXX.XX ₪"
    Returns 0.0 if no total found.
    """
    import re
    try:
        from openpyxl import load_workbook
        from io import BytesIO

        workbook = load_workbook(filename=BytesIO(xlsx_bytes), read_only=True, data_only=True)
        totals = []

        for sheet in workbook.worksheets:
            all_rows = list(sheet.iter_rows(values_only=True))

            # Check header rows (CAL format: "עסקאות לחיוב ב-XX/XX/XXXX: X,XXX.XX ₪")
            for row in all_rows[:5]:
                row_str = " ".join([str(c) for c in row if c])
                match = re.search(r'עסקאות\s*לחיוב.*?:\s*([\d,]+\.?\d*)\s*₪', row_str)
                if match:
                    amount_str = match.group(1).replace(",", "")
                    totals.append(float(amount_str))

            # Check footer rows (MAX format: "סך הכל" then amount on next row)
            for i, row in enumerate(all_rows):
                row_str = " ".join([str(c) for c in row if c])
                if "סך הכל" in row_str:
                    # Check same row for amount
                    match = re.search(r'([\d,]+\.?\d*)\s*₪', row_str)
                    if match:
                        amount_str = match.group(1).replace(",", "")
                        totals.append(float(amount_str))
                    # Check next row
                    elif i + 1 < len(all_rows):
                        next_row_str = " ".join([str(c) for c in all_rows[i + 1] if c])
                        match = re.search(r'([\d,]+\.?\d*)\s*₪?', next_row_str)
                        if match:
                            amount_str = match.group(1).replace(",", "")
                            try:
                                totals.append(float(amount_str))
                            except ValueError:
                                pass

        workbook.close()
        return sum(totals) if totals else 0.0
    except Exception as e:
        logger.error(f"Error extracting expected total from XLSX: {e}")
        return 0.0


def extract_expected_total_from_pdf(pdf_bytes: bytes) -> float:
    """
    Extract the expected total from a PDF CC statement.
    Looks for patterns like "סה\"כ חיוב לתאריך XX/XX/XX XXXX.XX"
    Returns 0.0 if no total found.
    """
    import re
    try:
        import pymupdf
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()

        totals = []

        # Pattern 1: "סה"כ חיוב לתאריך XX/XX/XX XXXX.XX"
        matches = re.findall(r'סה[״"\']כ\s*חיוב.*?(\d[\d,]*\.?\d*)', full_text, re.DOTALL)
        for m in matches:
            try:
                amount = float(m.replace(",", ""))
                if amount > 10:  # Filter out dates
                    totals.append(amount)
            except ValueError:
                pass

        # Pattern 2: Amount before "סה"כ"
        matches2 = re.findall(r'(\d[\d,]*\.?\d*)\s*₪?\s*סה[״"\']כ', full_text)
        for m in matches2:
            try:
                amount = float(m.replace(",", ""))
                if amount > 10:
                    totals.append(amount)
            except ValueError:
                pass

        return sum(totals) if totals else 0.0
    except ImportError:
        return 0.0
    except Exception as e:
        logger.error(f"Error extracting expected total from PDF: {e}")
        return 0.0


def extract_text_from_xlsx(xlsx_bytes: bytes) -> str:
    """
    Extract text from Excel (XLSX) bytes.
    Smart handling for Israeli credit card statements which have multiple amount columns.
    Specifically extracts only the charge amount (סכום חיוב) not the original amount (סכום עסקה מקורי).
    """
    try:
        from openpyxl import load_workbook
        from io import BytesIO

        workbook = load_workbook(filename=BytesIO(xlsx_bytes), read_only=True, data_only=True)
        lines = []

        for sheet in workbook.worksheets:
            # First, try to detect if this is an Israeli CC statement
            # by looking for characteristic Hebrew column headers
            header_row = None
            charge_amount_col = None
            original_amount_col = None

            for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                row_values = [str(cell) if cell is not None else "" for cell in row]
                row_text = " ".join(row_values)

                # Look for Israeli CC header row with "סכום חיוב"
                if "סכום חיוב" in row_text or "סכום העסקה" in row_text:
                    header_row = row_idx
                    for col_idx, cell in enumerate(row):
                        cell_str = str(cell) if cell else ""
                        if "סכום חיוב" in cell_str:
                            charge_amount_col = col_idx
                        elif "סכום עסקה מקורי" in cell_str or "סכום מקורי" in cell_str:
                            original_amount_col = col_idx
                    break

            # If we detected an Israeli CC format, extract smartly
            if header_row and charge_amount_col is not None:
                logger.info(f"Detected Israeli CC format. Charge col: {charge_amount_col}, Original col: {original_amount_col}")

                for row in sheet.iter_rows(min_row=header_row + 1, values_only=True):
                    if not any(cell is not None for cell in row):
                        continue

                    # Build cleaned row: include all columns EXCEPT the original amount column
                    cleaned_values = []
                    for col_idx, cell in enumerate(row):
                        # Skip the original amount column to avoid confusion
                        if original_amount_col is not None and col_idx == original_amount_col:
                            continue
                        # Also skip the currency column right after original amount
                        if original_amount_col is not None and col_idx == original_amount_col + 1:
                            if cell and "₪" in str(cell):
                                continue

                        if cell is not None:
                            cleaned_values.append(str(cell))

                    if cleaned_values:
                        lines.append(" ".join(cleaned_values))
            else:
                # Fallback to generic extraction
                for row in sheet.iter_rows(values_only=True):
                    row_values = [str(cell) if cell is not None else "" for cell in row]
                    if any(v.strip() for v in row_values):
                        lines.append(" ".join(row_values))

        workbook.close()
        return "\n".join(lines)
    except ImportError:
        logger.warning("openpyxl not installed - XLSX parsing unavailable")
        return ""
    except Exception as e:
        logger.error(f"XLSX extraction error: {e}")
        return ""


def save_transactions_to_db(transactions: list, sender_name: str) -> int:
    """Save transactions to database and return count."""
    saved_count = 0
    with Session(engine) as session:
        for tx in transactions:
            expense = Expense(
                amount=tx["amount"],
                description=tx["description"],
                category_id=tx["category_id"],
                payer=sender_name,
                is_fixed=False,
                source="file"
            )
            session.add(expense)
            saved_count += 1
        session.commit()
    return saved_count


def build_import_summary(transactions: list, expected_total: float = 0.0) -> tuple[str, str, float]:
    """Build summary text for bulk import. Returns (category_summary, validation_msg, diff_pct)."""
    total = sum(tx["amount"] for tx in transactions)
    categories = {}
    for tx in transactions:
        cat = tx["category_name"]
        categories[cat] = categories.get(cat, 0) + tx["amount"]

    category_summary = "\n".join([f"• {cat}: ₪{amt:,.2f}" for cat, amt in categories.items()])

    validation_msg = ""
    diff_pct = 0.0
    if expected_total > 0:
        diff = abs(total - expected_total)
        diff_pct = (diff / expected_total) * 100 if expected_total > 0 else 0

        if diff_pct <= 1:
            validation_msg = f"\n\n✅ *Validation: MATCH*\nFile total: ₪{expected_total:,.2f}"
        elif diff_pct <= 5:
            validation_msg = f"\n\n⚠️ *Validation: Close*\nFile total: ₪{expected_total:,.2f}\nDifference: ₪{diff:,.2f} ({diff_pct:.1f}%)"
        else:
            validation_msg = f"\n\n❌ *Validation: MISMATCH*\nFile total: ₪{expected_total:,.2f}\nParsed total: ₪{total:,.2f}\nDifference: ₪{diff:,.2f} ({diff_pct:.1f}%)"

    return category_summary, validation_msg, diff_pct


async def process_bulk_text(update: Update, text: str, sender_name: str, expected_total: float = 0.0):
    """Process bulk transaction text. On mismatch, ask for user confirmation before saving."""
    # Check if OpenAI is configured
    if not OPENAI_API_KEY:
        await update.message.reply_text(
            "⚠️ OpenAI API key not configured.\n"
            "Bulk import requires OpenAI for parsing.\n"
            "Please add openai_api_key in add-on configuration."
        )
        return

    transactions, error = parse_bulk_transactions(text)

    if not transactions:
        # Provide more helpful debugging info
        text_preview = text[:200].replace('\n', ' ')
        error_msg = f"\n\nError: {error}" if error else ""
        await update.message.reply_text(
            f"No transactions found in the text.{error_msg}\n\n"
            f"Text preview: {text_preview}...\n\n"
            f"Make sure the file contains transaction data with amounts."
        )
        return

    total = sum(tx["amount"] for tx in transactions)
    category_summary, validation_msg, diff_pct = build_import_summary(transactions, expected_total)

    # If mismatch (>5%), ask for confirmation before saving
    if expected_total > 0 and diff_pct > 5:
        # Store pending import
        import_id = str(uuid.uuid4())[:8]
        pending_imports[import_id] = {
            "transactions": transactions,
            "sender_name": sender_name,
            "chat_id": update.effective_chat.id,
            "expected_total": expected_total
        }

        # Build preview message with inline keyboard
        preview_reply = (
            f"*Bulk Import Preview*\n\n"
            f"Transactions: {len(transactions)}\n"
            f"Parsed Total: ₪{total:,.2f}\n\n"
            f"*By Category:*\n{category_summary}"
            f"{validation_msg}\n\n"
            f"⚠️ *There is a significant mismatch!*\n"
            f"Do you want to save these transactions anyway?"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ אשר ושמור", callback_data=f"import_approve_{import_id}"),
                InlineKeyboardButton("❌ בטל", callback_data=f"import_decline_{import_id}")
            ]
        ])

        await update.message.reply_text(preview_reply, parse_mode="Markdown", reply_markup=keyboard)
        return

    # No mismatch or mismatch <= 5% - save directly
    saved_count = save_transactions_to_db(transactions, sender_name)

    reply = (
        f"*Bulk Import Complete*\n\n"
        f"Transactions: {saved_count}\n"
        f"Total: ₪{total:,.2f}\n\n"
        f"*By Category:*\n{category_summary}"
        f"{validation_msg}"
    )
    await update.message.reply_text(reply, parse_mode="Markdown")


async def handle_import_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle approve/decline callbacks for bulk imports."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("import_"):
        return

    parts = data.split("_")
    if len(parts) != 3:
        return

    action = parts[1]  # "approve" or "decline"
    import_id = parts[2]

    # Check if import exists
    if import_id not in pending_imports:
        await query.edit_message_text(
            "❌ Import expired or already processed.\n"
            "Please upload the file again.",
            parse_mode="Markdown"
        )
        return

    pending = pending_imports.pop(import_id)
    transactions = pending["transactions"]
    sender_name = pending["sender_name"]
    expected_total = pending["expected_total"]

    if action == "decline":
        await query.edit_message_text(
            "❌ *Import Cancelled*\n\n"
            f"Discarded {len(transactions)} transactions.\n"
            "No data was saved.",
            parse_mode="Markdown"
        )
        return

    # action == "approve"
    saved_count = save_transactions_to_db(transactions, sender_name)
    total = sum(tx["amount"] for tx in transactions)
    category_summary, validation_msg, _ = build_import_summary(transactions, expected_total)

    reply = (
        f"✅ *Bulk Import Approved & Saved*\n\n"
        f"Transactions: {saved_count}\n"
        f"Total: ₪{total:,.2f}\n\n"
        f"*By Category:*\n{category_summary}"
        f"{validation_msg}"
    )
    await query.edit_message_text(reply, parse_mode="Markdown")


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
            is_fixed=False,
            source="manual"
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
    application.add_handler(CommandHandler("bulk", bulk_command))
    application.add_handler(CallbackQueryHandler(handle_import_callback, pattern="^import_"))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
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
