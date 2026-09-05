import os
import re
import logging
from typing import Tuple, Optional, List
from sqlmodel import Session, select
from backend.database import engine, KeywordMapping, Category

logger = logging.getLogger(__name__)

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
        import json

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a credit card statement parser. Extract all transactions from the text.\n"
                        f"For each transaction, extract:\n"
                        f"1. amount (numeric, positive value)\n"
                        f"2. description (merchant/business name)\n"
                        f"3. category (classify into one of: {categories_str})\n\n"
                        f"Return a JSON object with a 'transactions' array containing objects with keys: amount, description, category\n"
                        f"If you cannot find any transactions, return: {{\"transactions\": []}}"
                    )
                },
                {
                    "role": "user",
                    "content": text
                }
            ],
            max_tokens=8000,
            temperature=0,
            response_format={"type": "json_object"}  # Force valid JSON output
        )

        result_text = response.choices[0].message.content.strip()
        logger.info(f"LLM bulk parse response: {result_text[:200]}...")

        # Parse JSON response
        result = json.loads(result_text)
        transactions = result.get("transactions", [])

        if not isinstance(transactions, list):
            logger.warning("LLM did not return a list")
            return [], "Invalid response format"

        # Map category names to IDs
        parsed = []
        with Session(engine) as session:
            cat_map = {c.name: c.id for c in session.exec(select(Category)).all()}
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
                cat_name = tx.get("category", fallback_name)

                if amount is None or not isinstance(amount, (int, float)):
                    continue

                cat_id = cat_map.get(cat_name, fallback_id)
                if cat_name not in cat_map:
                    cat_name = fallback_name
                    cat_id = fallback_id

                parsed.append({
                    "amount": float(amount),
                    "description": str(desc),
                    "category_id": cat_id,
                    "category_name": cat_name
                })

        logger.info(f"Parsed {len(parsed)} transactions from bulk text")
        return parsed, ""

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM JSON response: {e}")
        return [], f"JSON parse error: {e}"
    except Exception as e:
        logger.error(f"Bulk transaction parsing failed: {e}")
        return [], f"OpenAI error: {e}"
