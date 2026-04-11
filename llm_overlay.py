"""
llm_overlay.py
──────────────
Phase 2: Claude as a second-opinion overlay on every passing signal.
Claude evaluates but does NOT block trades yet — verdict is logged only.
After 8-12 weeks, we compare Claude's accuracy vs outcomes to decide
whether to promote it to a gating role.

Adds to trades.csv:
  llm_approve    — true/false
  llm_conviction — 0.0 to 1.0
  llm_rationale  — one sentence
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
MODEL             = "claude-sonnet-4-20250514"
MAX_TOKENS        = 200


def _get_recent_outcomes(symbol: str, n: int = 5) -> str:
    """Get last N outcomes for this symbol from trades.csv."""
    try:
        df = pd.read_csv(CSV_PATH)
        sym_trades = df[
            (df["symbol"] == symbol) &
            (df["result"].isin(["win", "loss"]))
        ].tail(n)
        if sym_trades.empty:
            return "no history"
        outcomes = []
        for _, row in sym_trades.iterrows():
            outcomes.append(f"{row['result']}({row['pnl']:.1f}%)")
        return ", ".join(outcomes)
    except Exception:
        return "no history"


def _get_strategy_outcomes(strategy: str, n: int = 10) -> str:
    """Get last N outcomes for this strategy."""
    try:
        df = pd.read_csv(CSV_PATH)
        strat_trades = df[
            (df["strategy"] == strategy) &
            (df["result"].isin(["win", "loss"]))
        ].tail(n)
        if strat_trades.empty:
            return "no history"
        wins   = len(strat_trades[strat_trades["result"] == "win"])
        total  = len(strat_trades)
        wr     = wins / total * 100
        return f"{wins}/{total} wins ({wr:.0f}% win rate)"
    except Exception:
        return "no history"


def build_prompt(sym: str, signal: dict) -> str:
    """Build the evaluation prompt from signal data."""
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

    sym_history   = _get_recent_outcomes(sym)
    strat_history = _get_strategy_outcomes(strategy)

    return f"""You are a disciplined professional intraday trader reviewing a potential trade signal.
Evaluate objectively based on the technical data provided.

SIGNAL:
Symbol: {sym}
Direction: {direction}
Strategy: {strategy}
Score: {score}/100
Entry: ${entry:.2f}
R:R Ratio: {rrr:.2f}
ATR: {atr:.3f}

TECHNICALS:
RSI: {rsi:.1f}
Volume ratio vs avg: {vol_ratio:.2f}x
Price vs VWAP: {price_vs_vwap} (VWAP=${vwap:.2f})
EMA trend: {ema_trend} (EMA20=${ema_20:.2f}, EMA50=${ema_50:.2f})
ADX (trend strength): {adx:.1f}
MACD histogram: {macd_hist:.4f}
Signal notes: {notes}

RECENT HISTORY:
{sym} last 5 trades: {sym_history}
{strategy} last 10 trades: {strat_history}

Respond ONLY with valid JSON, no other text:
{{"approve": true_or_false, "conviction": 0.0_to_1.0, "rationale": "one sentence max 20 words"}}"""


def evaluate_signal(sym: str, signal: dict) -> dict:
    """
    Call Claude to evaluate a signal.
    Returns dict with approve, conviction, rationale.
    Never raises — returns neutral on any error.
    """
    neutral = {"approve": None, "conviction": 0.5, "rationale": "llm_unavailable"}

    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY not set — skipping LLM evaluation")
        return neutral

    try:
        prompt  = build_prompt(sym, signal)
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            body     = json.loads(resp.read())
            raw_text = body["content"][0]["text"].strip()

        # Parse JSON response
        result = json.loads(raw_text)
        approve    = bool(result.get("approve", False))
        conviction = float(result.get("conviction", 0.5))
        rationale  = str(result.get("rationale", ""))[:200]

        log.info(
            f"LLM [{sym}]: approve={approve} conviction={conviction:.2f} | {rationale}"
        )
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
    """
    Write LLM verdict back to the most recent open trade row for this symbol.
    Adds llm_approve, llm_conviction, llm_rationale columns.
    """
    try:
        df = pd.read_csv(CSV_PATH)

        # Ensure columns exist
        for col in ["llm_approve", "llm_conviction", "llm_rationale"]:
            if col not in df.columns:
                df[col] = None

        # Find the matching open row
        mask = (
            (df["symbol"] == sym) &
            (df["result"] == "open") &
            (df["timestamp"] == timestamp)
        )
        if mask.sum() == 0:
            # Try just symbol + open if timestamp doesn't match exactly
            mask = (df["symbol"] == sym) & (df["result"] == "open")

        if mask.sum() > 0:
            idx = df[mask].index[-1]
            df.at[idx, "llm_approve"]    = verdict["approve"]
            df.at[idx, "llm_conviction"] = verdict["conviction"]
            df.at[idx, "llm_rationale"]  = verdict["rationale"]
            df.to_csv(CSV_PATH, index=False)
            log.debug(f"LLM verdict written to CSV for {sym}")
    except Exception as e:
        log.error(f"Failed to write LLM verdict to CSV: {e}")


# ── Quick test ───────────────────────────────────────────────
if __name__ == "__main__":
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
    result = evaluate_signal("NVDA", test_signal)
    print(f"\nResult: {result}")
