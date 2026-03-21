"""
indicators.py
─────────────
Two completely separate indicator sets for two completely separate strategies.

SWING (Daily bars, 2–3 week horizon):
  200 EMA — long-term trend filter (true Varsity). Hard filter in checklist.
  50 EMA  — medium-term trend. Bonus if 20 EMA > 50 EMA.
  20 EMA  — fast trend for medium-term alignment bonus.
  MACD    — momentum supplement (low weight per Varsity).
  RSI-14  — oversold recovery zone 30-50 (true Varsity zone).
  ADX-14  — trend strength bonus (soft, not hard filter).
  ATR-14  — stop sizing.
  Support — 3-day rolling low (recent pullback level, not 10-day crash low).
  Support10 — 10-day rolling low (kept for reference/logging).
  Resistance — 10-day rolling high.
  Volume ratio — TIME-NORMALIZED so morning scans are fair vs EOD scans.

VOLUME NORMALIZATION FIX:
  Problem: At 11:30 AM only 2hrs of volume exists vs 10-day avg of full days.
  Raw vol_ratio at 11:30 AM ≈ 0.3 — never hits 1.2 threshold.
  Fix: Compare today's volume against (vol_avg * fraction_of_day_elapsed).
  At 11:30 AM (2/6.5 = 31% of day): compares vs 31% of avg daily volume.
  At 3:30 PM (6/6.5 = 92% of day): compares vs 92% of avg daily volume.
  Result: vol_ratio is now fair at any time of day.

SUPPORT FIX:
  Problem: 10-day low within 2% almost never true in a healthy uptrend.
  Fix: Use 3-day low (recent swing low) with 5% tolerance.
  Catches normal pullbacks in uptrends, not just near-crash entries.

INTRADAY (5-min bars, same-day close):
  VWAP    — anchor, hard filter.
  EMA 9/21 — ribbon for micro-trend direction.
  RSI-9   — fast exhaustion reads.
  ATR-9   — tight stop sizing.
  Support/Resistance — 10-bar rolling window.
  Volume ratio — normalized for intraday bars.
  Candlestick patterns — primary trigger on 5-min bars.
"""

import pandas as pd
import pandas_ta_compat as ta
import logging
from datetime import datetime
import pytz

log = logging.getLogger(__name__)


def _time_normalized_vol_ratio(df: pd.DataFrame) -> pd.Series:
    """
    Calculates volume ratio normalized for time of day.

    At 11:30 AM (2hrs into 6.5hr day = 30.8%):
      Compares today's volume against 30.8% of the 10-day average.
      So if avg daily volume is 1M, we expect ~308k by 11:30 AM.
      If today has 400k by 11:30 AM, ratio = 400k/308k = 1.3 ✅

    At 3:30 PM (6hrs into 6.5hr day = 92.3%):
      Compares today's volume against 92.3% of the 10-day average.
      Normal behaviour, close to raw ratio.

    Outside market hours (pre/post market or weekends):
      Falls back to raw ratio (day_fraction = 1.0).
    """
    now_et = datetime.now(pytz.timezone('America/New_York'))
    market_open  = now_et.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0,  second=0, microsecond=0)

    elapsed_secs = (now_et - market_open).total_seconds()
    total_secs   = (market_close - market_open).total_seconds()

    if elapsed_secs <= 0 or total_secs <= 0:
        day_fraction = 1.0   # outside market hours — use raw ratio
    else:
        day_fraction = min(elapsed_secs / total_secs, 1.0)

    if day_fraction < 0.05:
        day_fraction = 1.0   # too early, avoid division by tiny number

    expected_volume = df["vol_avg"] * day_fraction
    return df["volume"] / expected_volume.replace(0, float("nan"))


# ══════════════════════════════════════════════════════════════════════════════
# SWING — Daily indicators tuned for 2–3 week hold
# ══════════════════════════════════════════════════════════════════════════════

def calculate_swing_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Daily indicators for Varsity Grand Checklist swing trades.
    """
    # ── Long-term trend (Varsity hard filter) ─────────────────────────────
    df["ema_200"]    = ta.ema(df["close"], length=200)

    # ── Medium-term trend (alignment bonus) ───────────────────────────────
    df["ema_50"]     = ta.ema(df["close"], length=50)
    df["ema_20"]     = ta.ema(df["close"], length=20)
    df["ema_10"]     = ta.ema(df["close"], length=10)

    # ── MACD momentum (supplement, low weight) ────────────────────────────
    macd             = ta.macd(df["close"], fast=12, slow=26, signal=9)
    df["macd"]       = macd["MACD_12_26_9"]
    df["macd_signal"]= macd["MACDs_12_26_9"]
    df["macd_hist"]  = macd["MACDh_12_26_9"]

    # ── RSI — Varsity oversold zone 30-50 ─────────────────────────────────
    df["rsi"]        = ta.rsi(df["close"], length=14)

    # ── ADX — soft bonus only ─────────────────────────────────────────────
    adx              = ta.adx(df["high"], df["low"], df["close"], length=14)
    df["adx"]        = adx["ADX_14"]

    # ── ATR for stop sizing ───────────────────────────────────────────────
    df["atr"]        = ta.atr(df["high"], df["low"], df["close"], length=14)

    # ── S&R levels ────────────────────────────────────────────────────────
    # support: 3-day low — catches recent pullback levels in healthy uptrends
    # support10: 10-day low — kept for logging/reference
    # resistance: 10-day high — natural take-profit ceiling
    df["support"]    = df["low"].rolling(window=3).min()
    df["support10"]  = df["low"].rolling(window=10).min()
    df["resistance"] = df["high"].rolling(window=10).max()

    # ── Volume — time-normalized ──────────────────────────────────────────
    df["vol_avg"]    = df["volume"].rolling(window=10).mean()
    df["vol_ratio"]  = _time_normalized_vol_ratio(df)

    # ── Candlestick patterns (all 12) ─────────────────────────────────────
    df["engulfing"]  = ta.cdl_pattern(
        df["open"], df["high"], df["low"], df["close"]
    )
    return df


# ══════════════════════════════════════════════════════════════════════════════
# INTRADAY — 5-min indicators tuned for same-day close
# ══════════════════════════════════════════════════════════════════════════════

def calculate_intraday_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    5-minute indicators for intraday trading.
    Volume ratio uses raw ratio here — intraday bars are already
    normalized by nature (each 5-min bar vs 10-bar average of 5-min bars).
    """
    df["vwap"]       = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
    df["ema_9"]      = ta.ema(df["close"], length=9)
    df["ema_21"]     = ta.ema(df["close"], length=21)
    df["rsi"]        = ta.rsi(df["close"], length=9)
    df["atr"]        = ta.atr(df["high"], df["low"], df["close"], length=9)
    df["support"]    = df["low"].rolling(window=10).min()
    df["resistance"] = df["high"].rolling(window=10).max()

    # Raw volume ratio is fine for intraday (comparing 5-min bars to 5-min avg)
    df["vol_avg"]    = df["volume"].rolling(window=10).mean()
    df["vol_ratio"]  = df["volume"] / df["vol_avg"].replace(0, float("nan"))

    # All 12 candlestick patterns on 5-min bars
    df["engulfing"]  = ta.cdl_pattern(
        df["open"], df["high"], df["low"], df["close"]
    )
    return df
