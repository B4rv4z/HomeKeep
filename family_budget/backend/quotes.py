"""
Live stock quote fetcher using yfinance.

Uses the yfinance library which provides reliable access to Yahoo Finance data
with built-in rate limiting and retry handling.
"""
import logging
from datetime import datetime
from typing import Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Thread pool for running sync yfinance calls
_executor = ThreadPoolExecutor(max_workers=2)

# Cache for exchange rate (avoid too many requests)
_exchange_rate_cache = {
    "rate": None,
    "timestamp": None
}


def _fetch_quotes_sync(symbols: list[str]) -> dict[str, dict]:
    """
    Internal sync function to fetch quotes using yfinance.
    """
    if not symbols:
        return {}

    try:
        import yfinance as yf

        # Fetch all tickers at once (more efficient)
        tickers = yf.Tickers(" ".join(symbols))

        quotes = {}
        for symbol in symbols:
            try:
                ticker = tickers.tickers.get(symbol)
                if ticker:
                    info = ticker.fast_info
                    quotes[symbol] = {
                        "price": info.last_price if hasattr(info, 'last_price') else 0,
                        "change": 0,  # fast_info doesn't have change
                        "change_pct": 0,
                        "currency": info.currency if hasattr(info, 'currency') else "USD"
                    }
            except Exception as e:
                logger.warning(f"Error fetching {symbol}: {e}")
                continue

        logger.info(f"Fetched quotes for {len(quotes)} symbols via yfinance")
        return quotes

    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance")
        return {}
    except Exception as e:
        logger.error(f"Error fetching quotes: {e}")
        return {}


def _fetch_exchange_rate_sync() -> float:
    """
    Internal sync function to fetch USD/ILS rate using yfinance.
    """
    global _exchange_rate_cache

    # Check cache (valid for 5 minutes)
    if _exchange_rate_cache["rate"] and _exchange_rate_cache["timestamp"]:
        age = (datetime.now() - _exchange_rate_cache["timestamp"]).total_seconds()
        if age < 300:  # 5 minutes
            return _exchange_rate_cache["rate"]

    try:
        import yfinance as yf

        ticker = yf.Ticker("USDILS=X")
        info = ticker.fast_info
        rate = info.last_price if hasattr(info, 'last_price') else 3.65

        _exchange_rate_cache["rate"] = rate
        _exchange_rate_cache["timestamp"] = datetime.now()
        logger.info(f"USD/ILS rate: {rate}")
        return rate

    except ImportError:
        logger.error("yfinance not installed")
        return 3.65
    except Exception as e:
        logger.error(f"Error fetching USD/ILS rate: {e}")
        return _exchange_rate_cache.get("rate", 3.65)


async def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """
    Fetch live quotes for a list of stock symbols.

    Args:
        symbols: List of stock symbols (e.g., ["GOOGL", "MSFT", "ASML"])

    Returns:
        Dictionary mapping symbol to quote data:
        {
            "GOOGL": {
                "price": 345.02,
                "change": 5.50,
                "change_pct": 1.62,
                "currency": "USD"
            },
            ...
        }
    """
    if not symbols:
        return {}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _fetch_quotes_sync, symbols)


async def get_usd_ils_rate() -> float:
    """
    Get current USD/ILS exchange rate.

    Returns:
        Exchange rate (e.g., 3.65 means 1 USD = 3.65 ILS)
        Returns 3.65 as fallback if fetch fails.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _fetch_exchange_rate_sync)


def fetch_quotes_sync(symbols: list[str]) -> dict[str, dict]:
    """
    Synchronous version of fetch_quotes for use in non-async contexts.
    """
    return _fetch_quotes_sync(symbols)


def get_usd_ils_rate_sync() -> float:
    """
    Synchronous version of get_usd_ils_rate.
    """
    return _fetch_exchange_rate_sync()
