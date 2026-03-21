"""
logger.py v7 — Paper Trading
──────────────────────────────
CSV columns for strategy analysis:
  strategy   = swing_long / intraday_long / intraday_short
  timeframe  = swing / intraday
  direction  = long / short

get_daily_intraday_count() — tracks today's intraday trades for MAX_INTRADAY_TRADES limit
"""
import csv
import logging
import os
from datetime import datetime, date

TRADES_FILE = "trades.csv"

FIELDNAMES = [
    # Identity
    "timestamp", "date", "symbol",
    # Strategy split columns
    "strategy",     # swing_long / intraday_long / intraday_short
    "timeframe",    # swing / intraday
    "direction",    # long / short
    # Trade details
    "entry", "target", "stop", "qty", "rrr",
    # Score
    "score", "notes",
    # Pattern
    "pattern", "pattern_pts",
    # Support/Resistance
    "near_support", "support_val", "support10_val", "support_pts",
    # Volume
    "vol_surge", "vol_ratio", "vol_pts",
    # EMA
    "ema_aligned", "ema_20_val", "ema_50_val", "ema_200_val", "ema_pts",
    # RSI
    "rsi_fired", "rsi_val", "rsi_pts",
    # MACD (swing only)
    "macd_fired", "macd_hist", "macd_pts",
    # ADX (swing only)
    "adx_fired", "adx_val", "adx_pts",
    # VWAP (intraday only)
    "vwap_val",
    # ATR
    "atr",
    # Outcome
    "result", "pnl",
]

log = logging.getLogger(__name__)


def _parse_strategy(strategy: str) -> tuple[str, str]:
    if strategy == "swing_long":    return "swing",    "long"
    if strategy == "intraday_long": return "intraday", "long"
    if strategy == "intraday_short":return "intraday", "short"
    return "unknown", "unknown"


def log_trade(
    symbol: str, strategy: str,
    entry: float, target: float, stop: float,
    qty: float, rrr: float, score: int = 0,
    atr: float = None, breakdown: dict = None,
):
    bd = breakdown or {}
    timeframe, direction = _parse_strategy(strategy)
    file_exists = os.path.isfile(TRADES_FILE)
    try:
        with open(TRADES_FILE, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "timestamp":     datetime.now().isoformat(timespec="seconds"),
                "date":          date.today().isoformat(),
                "symbol":        symbol,
                "strategy":      strategy,
                "timeframe":     timeframe,
                "direction":     direction,
                "entry":         round(entry,  4),
                "target":        round(target, 4),
                "stop":          round(stop,   4),
                "qty":           round(qty,    6),
                "rrr":           round(rrr,    2),
                "score":         score,
                "notes":         bd.get("notes", ""),
                "pattern":       bd.get("pattern", ""),
                "pattern_pts":   bd.get("pattern_pts", 0),
                "near_support":  bd.get("near_support", ""),
                "support_val":   bd.get("support_val", ""),
                "support10_val": bd.get("support10_val", ""),
                "support_pts":   bd.get("support_pts", 0),
                "vol_surge":     bd.get("vol_surge", ""),
                "vol_ratio":     bd.get("vol_ratio", ""),
                "vol_pts":       bd.get("vol_pts", 0),
                "ema_aligned":   bd.get("ema_aligned", ""),
                "ema_20_val":    bd.get("ema_20_val", ""),
                "ema_50_val":    bd.get("ema_50_val", ""),
                "ema_200_val":   bd.get("ema_200_val", ""),
                "ema_pts":       bd.get("ema_pts", 0),
                "rsi_fired":     bd.get("rsi_fired", ""),
                "rsi_val":       bd.get("rsi_val", ""),
                "rsi_pts":       bd.get("rsi_pts", 0),
                "macd_fired":    bd.get("macd_fired", ""),
                "macd_hist":     bd.get("macd_hist", ""),
                "macd_pts":      bd.get("macd_pts", 0),
                "adx_fired":     bd.get("adx_fired", ""),
                "adx_val":       bd.get("adx_val", ""),
                "adx_pts":       bd.get("adx_pts", 0),
                "vwap_val":      bd.get("vwap_val", ""),
                "atr":           round(atr, 4) if atr is not None else "",
                "result":        "open",
                "pnl":           "",
            })
    except Exception as e:
        log.error(f"Trade log write failed: {e}")


def get_daily_pnl() -> float:
    today = date.today().isoformat()
    total = 0.0
    if not os.path.isfile(TRADES_FILE):
        return total
    try:
        with open(TRADES_FILE, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("date") == today and row.get("pnl"):
                    total += float(row["pnl"])
    except Exception as e:
        log.error(f"Daily P&L read failed: {e}")
    return total


def get_daily_intraday_count() -> int:
    """Counts intraday trades placed today. Used to enforce MAX_INTRADAY_TRADES."""
    today = date.today().isoformat()
    count = 0
    if not os.path.isfile(TRADES_FILE):
        return 0
    try:
        with open(TRADES_FILE, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("date") == today and row.get("timeframe") == "intraday":
                    count += 1
    except Exception as e:
        log.error(f"Daily intraday count failed: {e}")
    return count


def get_swing_entry_dates() -> dict:
    from datetime import date as date_type
    entries = {}
    if not os.path.isfile(TRADES_FILE):
        return entries
    try:
        with open(TRADES_FILE, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("timeframe") == "swing" and row.get("result") == "open":
                    sym = row["symbol"]
                    try:
                        entry_date = date_type.fromisoformat(row["date"])
                        if sym not in entries or entry_date < entries[sym]:
                            entries[sym] = entry_date
                    except ValueError:
                        pass
    except Exception as e:
        log.error(f"Swing entry dates read failed: {e}")
    return entries
