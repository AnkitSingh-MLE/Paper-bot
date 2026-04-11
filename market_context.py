"""
market_context.py
─────────────────
Fetches two free real-time context signals for the LLM prompt:

1. Alpaca News API — recent headlines for the symbol (last 6 hours)
2. SEC EDGAR Form 4 — insider buying/selling (last 30 days)

Both are completely free. No API keys needed beyond what you already have.
Called by llm_overlay.py before building the prompt.
"""

import os
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")

# ── 1. ALPACA NEWS ────────────────────────────────────────────

def get_recent_news(symbol: str, hours: int = 6) -> str:
    """
    Fetch recent news headlines for a symbol from Alpaca News API.
    Returns a formatted string for the LLM prompt.
    Free with any Alpaca account.
    """
    if not ALPACA_API_KEY:
        return "news unavailable"

    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        url = (
            f"https://data.alpaca.markets/v1beta1/news"
            f"?symbols={symbol}&start={since}&limit=5&sort=desc"
        )
        req = urllib.request.Request(
            url,
            headers={
                "APCA-API-KEY-ID":     ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())

        articles = data.get("news", [])
        if not articles:
            return "no recent news"

        headlines = []
        for a in articles[:3]:
            headline  = a.get("headline", "")[:100]
            published = a.get("created_at", "")[:10]
            sentiment = a.get("symbols", [{}])
            headlines.append(f"• [{published}] {headline}")

        return "\n".join(headlines)

    except Exception as e:
        log.debug(f"News fetch failed for {symbol}: {e}")
        return "news unavailable"


# ── 2. SEC EDGAR INSIDER TRADING (FORM 4) ───────────────────

def get_insider_activity(symbol: str, days: int = 30) -> str:
    """
    Fetch recent insider buying/selling from SEC EDGAR for a symbol.
    Form 4 filings = what executives and directors actually did with shares.
    Completely free, no API key needed.
    """
    try:
        # Step 1: Get CIK number for the symbol
        search_url = (
            f"https://efts.sec.gov/LATEST/search-index?q=%22{symbol}%22"
            f"&dateRange=custom&startdt={(datetime.now()-timedelta(days=days)).strftime('%Y-%m-%d')}"
            f"&enddt={datetime.now().strftime('%Y-%m-%d')}"
            f"&forms=4"
        )
        req = urllib.request.Request(
            search_url,
            headers={"User-Agent": "PaperBot research@paperbot.com"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())

        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return "no insider filings found"

        # Parse first 3 filings
        activities = []
        for hit in hits[:3]:
            source     = hit.get("_source", {})
            filed      = source.get("file_date", "")[:10]
            filer_name = source.get("display_names", ["unknown"])[0]
            # Extract transaction type from form description
            desc       = source.get("period_of_report", "")
            activities.append(f"• [{filed}] {filer_name} filed Form 4")

        if not activities:
            return "no recent insider activity"

        return "\n".join(activities)

    except Exception as e:
        log.debug(f"SEC insider fetch failed for {symbol}: {e}")
        return "insider data unavailable"


def get_market_context(symbol: str) -> dict:
    """
    Main entry point — returns dict with news and insider context.
    Called by llm_overlay.py before building the prompt.
    Never raises — returns empty strings on any failure.
    """
    log.debug(f"Fetching market context for {symbol}...")

    news    = get_recent_news(symbol)
    insider = get_insider_activity(symbol)

    return {
        "news":    news,
        "insider": insider,
    }


# ── Quick test ───────────────────────────────────────────────
if __name__ == "__main__":
    from dotenv import load_dotenv
    import os
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

    # Re-load after dotenv
    import importlib, sys
    if "market_context" in sys.modules:
        importlib.reload(sys.modules["market_context"])

    logging.basicConfig(level=logging.INFO)

    test_symbols = ["NVDA", "AAPL", "TSLA"]
    for sym in test_symbols:
        print(f"\n{'='*50}")
        print(f"Symbol: {sym}")
        ctx = get_market_context(sym)
        print(f"\nNEWS:\n{ctx['news']}")
        print(f"\nINSIDER ACTIVITY:\n{ctx['insider']}")
