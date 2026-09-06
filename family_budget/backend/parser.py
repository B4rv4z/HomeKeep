import os
import re
import json
import logging
from typing import Tuple, Optional, List
from sqlmodel import Session, select
from backend.database import engine, KeywordMapping, Category

logger = logging.getLogger(__name__)


def repair_json(text: str) -> Optional[dict]:
    """
    Attempt to repair and parse potentially malformed JSON.
    Returns parsed dict or None if repair fails.
    """
    # First try direct parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON object from text (in case there's extra content)
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Try to fix common issues
    cleaned = text

    # Remove any BOM or special characters at start
    cleaned = cleaned.lstrip('\ufeff\u200b\u200c\u200d')

    # Try to find and extract just the transactions array
    tx_match = re.search(r'"transactions"\s*:\s*\[([\s\S]*?)\]', cleaned)
    if tx_match:
        try:
            # Reconstruct minimal JSON
            return json.loads('{"transactions": [' + tx_match.group(1) + ']}')
        except json.JSONDecodeError:
            pass

    # Last resort: try to extract individual transaction objects
    tx_objects = re.findall(r'\{[^{}]*"amount"[^{}]*\}', cleaned)
    if tx_objects:
        transactions = []
        for tx_str in tx_objects:
            try:
                tx = json.loads(tx_str)
                if "amount" in tx:
                    transactions.append(tx)
            except json.JSONDecodeError:
                continue
        if transactions:
            return {"transactions": transactions}

    return None

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Cache for OpenAI client (lazy initialization)
_openai_client = None


def get_openai_client():
    """Lazy initialization of OpenAI client."""
    global _openai_client
    if _openai_client is None and OPENAI_API_KEY:
        try:
            from openai import OpenAI
            _openai_client = OpenAI(api_key=OPENAI_API_KEY)
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
    return _openai_client


def get_category_names() -> List[str]:
    """Get all category names from database."""
    with Session(engine) as session:
        categories = session.exec(select(Category)).all()
        return [cat.name for cat in categories]


def classify_with_llm(description: str) -> Optional[str]:
    """
    Use OpenAI to classify an expense description into a category.
    Returns the category name or None if classification fails.
    """
    client = get_openai_client()
    if not client:
        return None

    categories = get_category_names()
    categories_str = ", ".join(categories)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Fast and cheap
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a expense classifier. Given an expense description, "
                        f"classify it into exactly one of these categories: {categories_str}. "
                        f"Reply with ONLY the category name, nothing else. "
                        f"If unsure, reply with 'General & Miscellaneous'."
                    )
                },
                {
                    "role": "user",
                    "content": description
                }
            ],
            max_tokens=50,
            temperature=0
        )

        category_name = response.choices[0].message.content.strip()
        logger.info(f"LLM classified '{description}' as '{category_name}'")

        # Validate it's a real category
        if category_name in categories:
            return category_name
        else:
            logger.warning(f"LLM returned unknown category: {category_name}")
            return None

    except Exception as e:
        logger.error(f"OpenAI classification failed: {e}")
        return None


def parse_expense_text(text: str) -> Tuple[Optional[float], str, int, str]:
    """
    Extract amount and classify expense into a category.

    Classification priority:
    1. Keyword matching (fast, free)
    2. LLM classification via OpenAI (smart fallback)
    3. Default to "General & Miscellaneous"

    Args:
        text: Raw message text from Telegram (e.g., "coffee 25" or "150 groceries")

    Returns:
        Tuple of (amount, description, category_id, category_name)
        Returns (None, text, 0, "Unknown") if no amount found
    """
    text = text.strip()

    # Match integer or decimal amount anywhere in the text
    amount_match = re.search(r"(\d+(?:\.\d+)?)", text)

    if not amount_match:
        return None, text, 0, "Unknown"

    amount = float(amount_match.group(1))

    # Clean description by removing the numerical token
    clean_desc = re.sub(r"\d+(?:\.\d+)?", "", text).strip()
    if not clean_desc:
        clean_desc = "General Expense"

    # Normalize whitespace
    clean_desc = " ".join(clean_desc.split())

    with Session(engine) as session:
        # Get fallback category
        fallback = session.exec(
            select(Category).where(Category.name == "General & Miscellaneous")
        ).first()
        fallback_id = fallback.id if fallback else 1
        fallback_name = fallback.name if fallback else "General & Miscellaneous"

        # Step 1: Try keyword matching first (fast, free)
        mappings = session.exec(select(KeywordMapping)).all()
        text_lower = clean_desc.lower()

        for mapping in mappings:
            pattern = r"\b" + re.escape(mapping.keyword.lower()) + r"\b"
            if re.search(pattern, text_lower):
                matched_cat = session.get(Category, mapping.category_id)
                if matched_cat:
                    logger.info(f"Keyword match: '{clean_desc}' -> '{matched_cat.name}'")
                    return amount, clean_desc, matched_cat.id, matched_cat.name

        # Step 2: Try LLM classification (smart fallback)
        if OPENAI_API_KEY:
            llm_category = classify_with_llm(clean_desc)
            if llm_category:
                # Find the category in database
                cat = session.exec(
                    select(Category).where(Category.name == llm_category)
                ).first()
                if cat:
                    return amount, clean_desc, cat.id, cat.name

        # Step 3: Default fallback
        logger.info(f"No match for '{clean_desc}', using fallback")
        return amount, clean_desc, fallback_id, fallback_name


def extract_amount_only(text: str) -> Optional[float]:
    """
    Extract just the numerical amount from text.
    Useful for validation or quick parsing.
    """
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def extract_keywords_from_description(description: str) -> List[str]:
    """
    Extract meaningful keywords from an expense description for learning.

    Strategy:
    1. Clean and normalize the text
    2. Extract significant words (length >= 3, not numbers)
    3. Also extract the full description as a keyword for exact matching

    Returns:
        List of keywords to save for category mapping
    """
    if not description:
        return []

    # Normalize whitespace
    text = " ".join(description.strip().split())

    keywords = []

    # Add full description as primary keyword (for exact matches)
    if len(text) >= 3:
        keywords.append(text.lower())

    # Extract individual significant words
    words = text.split()
    for word in words:
        # Clean word of punctuation
        clean_word = re.sub(r'[^\w\u0590-\u05FF]', '', word)  # Keep Hebrew and alphanumeric

        # Skip short words and numbers
        if len(clean_word) >= 3 and not clean_word.isdigit():
            lower_word = clean_word.lower()
            if lower_word not in keywords:
                keywords.append(lower_word)

    return keywords


def learn_category_from_correction(description: str, new_category_id: int) -> dict:
    """
    Learn from a user's category correction by saving keywords to KeywordMapping.

    When a user changes the category of an expense, this function:
    1. Extracts keywords from the expense description
    2. Saves them to KeywordMapping for future auto-categorization

    Args:
        description: The expense description to learn from
        new_category_id: The correct category ID the user assigned

    Returns:
        dict with 'keywords_added' count and 'keywords_updated' count
    """
    keywords = extract_keywords_from_description(description)

    if not keywords:
        return {"keywords_added": 0, "keywords_updated": 0}

    added = 0
    updated = 0

    with Session(engine) as session:
        for keyword in keywords:
            # Check if keyword already exists
            existing = session.exec(
                select(KeywordMapping).where(KeywordMapping.keyword == keyword)
            ).first()

            if existing:
                # Update if category changed
                if existing.category_id != new_category_id:
                    existing.category_id = new_category_id
                    session.add(existing)
                    updated += 1
                    logger.info(f"Updated keyword mapping: '{keyword}' -> category_id={new_category_id}")
            else:
                # Add new mapping
                new_mapping = KeywordMapping(
                    keyword=keyword,
                    category_id=new_category_id
                )
                session.add(new_mapping)
                added += 1
                logger.info(f"Added keyword mapping: '{keyword}' -> category_id={new_category_id}")

        session.commit()

    return {"keywords_added": added, "keywords_updated": updated}


def get_category_by_keywords(description: str) -> Optional[Tuple[int, str]]:
    """
    Try to find a category by matching learned keywords.

    Args:
        description: The expense description to match

    Returns:
        Tuple of (category_id, category_name) if found, None otherwise
    """
    if not description:
        return None

    text_lower = description.lower().strip()

    with Session(engine) as session:
        mappings = session.exec(select(KeywordMapping)).all()

        # Try exact match first (full description)
        for mapping in mappings:
            if mapping.keyword == text_lower:
                cat = session.get(Category, mapping.category_id)
                if cat:
                    logger.info(f"Exact keyword match: '{description}' -> '{cat.name}'")
                    return cat.id, cat.name

        # Try word-level matching
        for mapping in mappings:
            pattern = r"\b" + re.escape(mapping.keyword) + r"\b"
            if re.search(pattern, text_lower):
                cat = session.get(Category, mapping.category_id)
                if cat:
                    logger.info(f"Keyword match: '{description}' -> '{cat.name}' (keyword: {mapping.keyword})")
                    return cat.id, cat.name

        return None


def clean_pdf_text(text: str) -> str:
    """
    Clean PDF extracted text to make it easier for LLM to parse.
    Removes noise, normalizes formatting, and rejoins fragmented Hebrew text.
    """
    # Remove common PDF artifacts
    text = re.sub(r'\x00', '', text)  # Null bytes
    text = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f]', '', text)  # Control chars

    # Normalize whitespace but keep newlines for structure
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Remove very long lines that are likely garbage (e.g., base64 encoded images)
    lines = text.split('\n')
    cleaned_lines = [line.strip() for line in lines if len(line) < 500]

    # Rejoin fragmented Hebrew text lines
    # Israeli CC PDFs often split text like "חברת החשמל לישראל" across multiple lines
    # Join consecutive short lines that look like fragments
    rejoined_lines = []
    buffer = []

    for line in cleaned_lines:
        # Skip empty lines - they mark section boundaries
        if not line:
            if buffer:
                rejoined_lines.append(' '.join(buffer))
                buffer = []
            rejoined_lines.append('')
            continue

        # Check if line looks like a fragment (short, no numbers, Hebrew text)
        is_fragment = (
            len(line) < 15 and
            not re.search(r'\d', line) and
            re.search(r'[\u0590-\u05FF]', line)  # Contains Hebrew
        )

        # Check if line has a transaction amount (likely complete or end of transaction)
        has_amount = bool(re.search(r'\d+[.,]\d{2}', line))

        if is_fragment and not has_amount:
            buffer.append(line)
        else:
            if buffer:
                # Join buffer with current line
                buffer.append(line)
                rejoined_lines.append(' '.join(buffer))
                buffer = []
            else:
                rejoined_lines.append(line)

    # Don't forget any remaining buffer
    if buffer:
        rejoined_lines.append(' '.join(buffer))

    text = '\n'.join(rejoined_lines)
    return text.strip()


def parse_bulk_transactions(text: str) -> tuple[List[dict], str]:
    """
    Parse bulk credit card transactions using OpenAI.

    Args:
        text: Raw text from CC statement (could be copy-pasted, PDF text, etc.)

    Returns:
        Tuple of (transactions list, error message or empty string)
    """
    client = get_openai_client()
    if not client:
        logger.warning("OpenAI not configured, cannot parse bulk transactions")
        return [], "OpenAI not configured"

    categories = get_category_names()
    categories_str = ", ".join(categories)

    try:
        # Clean the PDF text first
        text = clean_pdf_text(text)
        logger.info(f"Cleaned text length: {len(text)} chars")

        # Truncate text if too long (OpenAI has token limits)
        max_chars = 10000
        if len(text) > max_chars:
            text = text[:max_chars]
            logger.info(f"Truncated text to {max_chars} characters")

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are an Israeli credit card statement parser. Extract ALL financial transactions from the Hebrew text.\n\n"
                        f"IMPORTANT: Hebrew PDF text may be fragmented across lines due to RTL formatting. "
                        f"Merchant names like 'חברת החשמל לישראל' may appear split. Reconstruct full names.\n\n"
                        f"CRITICAL - WHICH AMOUNT TO USE:\n"
                        f"Israeli CC statements often show TWO amounts per transaction:\n"
                        f"- 'סכום עסקה' (transaction amount) - the original/exact amount\n"
                        f"- 'סכום חיוב' (charge amount) - the rounded amount actually charged\n\n"
                        f"ALWAYS use 'סכום חיוב' (charge amount) - this is the SECOND amount column in CAL/Mastercard statements.\n"
                        f"Example: If you see '5.85 6.0', use 6.0 (the charge amount, NOT 5.85)\n"
                        f"Example: If you see '496.3 497.0', use 497.0 (the charge amount, NOT 496.3)\n\n"
                        f"FOR INSTALLMENT PAYMENTS (תשלומים) in MAX statements:\n"
                        f"- Use the smaller amount which is the monthly installment charge\n"
                        f"- Example: '78 ₪ 780 ₪' means monthly charge is 78, use 78 NOT 780\n\n"
                        f"RULES:\n"
                        f"1. Find ALL transaction lines with amounts (numbers like 123.45 or 123)\n"
                        f"2. Extract the full merchant/business name as description (rejoin fragmented text)\n"
                        f"3. amount must be a positive number (no currency symbols)\n"
                        f"4. For NEGATIVE amounts (זיכוי/refunds with minus sign), use the negative value as-is\n"
                        f"5. Classify each into one of: {categories_str}\n"
                        f"6. If unsure about category, use 'כללי ושונות'\n"
                        f"7. DO NOT skip any transactions - extract every single one with an amount\n"
                        f"8. Each transaction should appear ONCE - do not create duplicates\n"
                        f"9. Extract the transaction date (תאריך עסקה) for each transaction in YYYY-MM-DD format\n"
                        f"   - Israeli dates are typically DD/MM/YY or DD-MM-YYYY format - convert to YYYY-MM-DD\n"
                        f"   - If year is 2-digit (e.g., 26), assume 20XX (2026)\n"
                        f"   - If date is not found, use null\n\n"
                        f"Return valid JSON: {{\"transactions\": [{{\"amount\": 123.45, \"description\": \"Store\", \"category\": \"קטגוריה\", \"date\": \"2026-01-15\"}}]}}"
                    )
                },
                {
                    "role": "user",
                    "content": f"Extract ALL transactions from this Israeli credit card statement:\n\n{text}"
                }
            ],
            max_tokens=4000,
            temperature=0,
            response_format={"type": "json_object"}
        )

        result_text = response.choices[0].message.content.strip()
        logger.info(f"LLM bulk parse response length: {len(result_text)} chars")
        logger.info(f"LLM response preview: {result_text[:300]}...")

        # Use repair_json for robust parsing
        result = repair_json(result_text)
        if result is None:
            logger.error(f"Failed to parse/repair JSON. Raw response: {result_text[:500]}")
            return [], f"JSON parse error - could not repair response"

        transactions = result.get("transactions", [])

        if not isinstance(transactions, list):
            logger.warning("LLM did not return a list")
            return [], "Invalid response format"

        # Map category names to IDs, applying learned keyword mappings
        parsed = []
        learned_matches = 0
        with Session(engine) as session:
            cat_map = {c.name: c.id for c in session.exec(select(Category)).all()}
            cat_id_map = {c.id: c.name for c in session.exec(select(Category)).all()}
            fallback = session.exec(
                select(Category).where(Category.name == "כללי ושונות")
            ).first()
            fallback_id = fallback.id if fallback else 1
            fallback_name = fallback.name if fallback else "כללי ושונות"

            for tx in transactions:
                if not isinstance(tx, dict):
                    continue
                amount = tx.get("amount")
                desc = tx.get("description", "Unknown")
                llm_cat_name = tx.get("category", fallback_name)
                tx_date = tx.get("date")  # YYYY-MM-DD format or null

                if amount is None or not isinstance(amount, (int, float)):
                    continue

                # PRIORITY: Check learned keyword mappings first
                # This allows user corrections to override LLM classifications
                keyword_match = get_category_by_keywords(str(desc))
                if keyword_match:
                    cat_id, cat_name = keyword_match
                    learned_matches += 1
                    logger.info(f"Using learned category for '{desc}': {cat_name} (LLM suggested: {llm_cat_name})")
                else:
                    # Fall back to LLM classification
                    cat_id = cat_map.get(llm_cat_name, fallback_id)
                    cat_name = llm_cat_name
                    if llm_cat_name not in cat_map:
                        cat_name = fallback_name
                        cat_id = fallback_id

                parsed.append({
                    "amount": float(amount),
                    "description": str(desc),
                    "category_id": cat_id,
                    "category_name": cat_name,
                    "transaction_date": tx_date  # Can be None or YYYY-MM-DD string
                })

        if learned_matches > 0:
            logger.info(f"Applied learned keyword mappings to {learned_matches}/{len(parsed)} transactions")

        logger.info(f"Parsed {len(parsed)} transactions from bulk text")
        return parsed, ""

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM JSON response: {e}")
        return [], f"JSON parse error: {e}"
    except Exception as e:
        logger.error(f"Bulk transaction parsing failed: {e}")
        return [], f"OpenAI error: {e}"
