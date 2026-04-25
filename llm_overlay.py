"""
llm_overlay.py
──────────────
Phase 2: Claude as a second-opinion overlay on every passing signal.
Claude evaluates but does NOT block trades yet — verdict is logged only.
Now includes: news headlines + SEC insider activity in the prompt.
"""

import os
import json
import logging
import urllib.request
import urllib.error
import pandas as pd
from datetime import datetime

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "trades.csv")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL             = "claude-sonnet-4-6"
MAX_TOKENS        = 200


def build_prompt(sym: str, signal: dict, context: dict) -> str:
    direction  = "LONG" if not signal.get("is_short") else "SHORT"
    strategy   = signal.get("strategy", "intraday")
    entry      = signal.get("entry", signal.get("close", 0))
    score      = signal.get("score", 0)
    rsi        = signal.get("rsi_val", 0)
    vol_ratio  = signal.get("vol_ratio", 0)
    vwap       = signal.get("vwap_val", 0)
    ema_20     = signal.get("ema_20_val", 0)
    ema_50     = signal.get("ema_50_val", 0)
    adx        = signal.get("adx_val", 0)
    macd_hist  = signal.get("macd_hist", 0)
    notes      = signal.get("notes", "")
    rrr        = signal.get("rrr", 0)
    atr        = signal.get("atr", 0)

    price_vs_vwap = "above" if entry > vwap else "below"
    ema_trend     = "aligned bullish" if ema_20 > ema_50 else "aligned bearish"

    news    = context.get("news", "unavailable")
    insider = context.get("insider", "unavailable")

    return f"""You are a disciplined professional intraday trader reviewing a trade signal.
Evaluate based on technicals and market context only.

SIGNAL:
Symbol: {sym} | Direction: {direction} | Strategy: {strategy}
Score: {score}/100 | Entry: ${entry:.2f} | R:R: {rrr:.2f} | ATR: {atr:.3f}

TECHNICALS:
RSI: {rsi:.1f} | Volume ratio: {vol_ratio:.2f}x avg
Price vs VWAP: {price_vs_vwap} (VWAP=${vwap:.2f})
EMA trend: {ema_trend} (EMA20=${ema_20:.2f}, EMA50=${ema_50:.2f})
ADX: {adx:.1f} | MACD histogram: {macd_hist:.4f}
Signal notes: {notes}

MARKET CONTEXT:
Recent news for {sym}:
{news}

Insider activity (last 30 days):
{insider}

Respond ONLY with valid JSON, no other text:
{{"approve": true_or_false, "conviction": 0.0_to_1.0, "rationale": "one sentence max 20 words"}}"""


def evaluate_signal(sym: str, signal: dict) -> dict:
    neutral = {"approve": None, "conviction": 0.5, "rationale": "llm_unavailable"}

    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY not set — skipping LLM evaluation")
        return neutral

    try:
        from market_context import get_market_context
        context = get_market_context(sym)
    except Exception as e:
        log.warning(f"Market context failed for {sym}: {e}")
        context = {"news": "unavailable", "insider": "unavailable"}

    try:
        prompt  = build_prompt(sym, signal, context)
        payload = {
            "model":      MODEL,
            "max_tokens": MAX_TOKENS,
            "messages":   [{"role": "user", "content": prompt}]
        }
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=data,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body     = json.loads(resp.read())
            raw_text = body["content"][0]["text"].strip()

        result     = json.loads(raw_text)
        approve    = bool(result.get("approve", False))
        conviction = float(result.get("conviction", 0.5))
        rationale  = str(result.get("rationale", ""))[:200]

        log.info(f"LLM [{sym}]: approve={approve} conviction={conviction:.2f} | {rationale}")
        log.info(f"LLM [{sym}] context — news: {context['news'][:80]}...")
        return {"approve": approve, "conviction": conviction, "rationale": rationale}

    except json.JSONDecodeError as e:
        log.warning(f"LLM [{sym}]: JSON parse error — {e}")
        return neutral
    except urllib.error.URLError as e:
        log.warning(f"LLM [{sym}]: API call failed — {e}")
        return neutral
    except Exception as e:
        log.warning(f"LLM [{sym}]: unexpected error — {e}")
        return neutral


def write_llm_verdict_to_csv(sym: str, timestamp: str, verdict: dict):
    try:
        df = pd.read_csv(CSV_PATH)
        for col in ["llm_approve", "llm_conviction", "llm_rationale"]:
            if col not in df.columns:
                df[col] = None
        mask = (df["symbol"] == sym) & (df["result"] == "open")
        if mask.sum() > 0:
            idx = df[mask].index[-1]
            df.at[idx, "llm_approve"]    = verdict["approve"]
            df.at[idx, "llm_conviction"] = verdict["conviction"]
            df.at[idx, "llm_rationale"]  = verdict["rationale"]
            df.to_csv(CSV_PATH, index=False)
    except Exception as e:
        log.error(f"Failed to write LLM verdict to CSV: {e}")


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

    logging.basicConfig(level=logging.INFO)

    test_signal = {
        "is_short":   False,
        "strategy":   "intraday_long",
        "entry":      177.50,
        "score":      88,
        "rsi_val":    54.2,
        "vol_ratio":  2.1,
        "vwap_val":   176.80,
        "ema_20_val": 175.00,
        "ema_50_val": 172.00,
        "adx_val":    28.5,
        "macd_hist":  0.0234,
        "notes":      "orb_break+25 | ema_trend+20 | above_vwap+20 | vol_surge_2x+20",
        "rrr":        2.1,
        "atr":        0.487,
    }
    print("\nTesting with full market context...")
    result = evaluate_signal("NVDA", test_signal)
    print(f"\nFinal verdict: {result}")