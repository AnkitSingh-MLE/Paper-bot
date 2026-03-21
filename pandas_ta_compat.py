"""
pandas_ta_compat.py
───────────────────
Drop-in wrapper using the 'ta' library since pandas_ta is unavailable on PyPI.
Provides identical function signatures to pandas_ta so indicators.py needs no changes.

Candlestick patterns detected (all vectorized — no Python loops):

BULLISH (return +N, used for LONG entries):
  +6  Bullish Engulfing  — green candle fully wraps previous red candle
  +5  Morning Star       — 3-candle reversal: red, doji, strong green
  +5  Marubozu Bullish   — almost no wicks, strong conviction green candle
  +4  Hammer             — small body at top, long lower wick (2x body)
  +3  Piercing Line      — green candle closes above midpoint of previous red
  +2  Bullish Harami     — small green candle inside previous large red candle

BEARISH (return -N, used for SHORT entries):
  -6  Bearish Engulfing  — red candle fully wraps previous green candle
  -5  Evening Star       — 3-candle reversal: green, doji, strong red
  -5  Marubozu Bearish   — almost no wicks, strong conviction red candle
  -4  Shooting Star      — small body at bottom, long upper wick (2x body)
  -3  Dark Cloud Cover   — red candle closes below midpoint of previous green
  -2  Bearish Harami     — small red candle inside previous large green candle

SHORT SELLING is currently disabled in config.py (ENABLE_SHORT_SELLING=False).
Bearish patterns are detected and stored but will not trigger orders until enabled.
"""

import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator, ADXIndicator
from ta.volatility import AverageTrueRange


def ema(series: pd.Series, length: int = 10) -> pd.Series:
    return EMAIndicator(close=series, window=length).ema_indicator()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    return RSIIndicator(close=series, window=length).rsi()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    m = MACD(close=series, window_fast=fast, window_slow=slow, window_sign=signal)
    result = pd.DataFrame(index=series.index)
    result[f"MACD_{fast}_{slow}_{signal}"]  = m.macd()
    result[f"MACDs_{fast}_{slow}_{signal}"] = m.macd_signal()
    result[f"MACDh_{fast}_{slow}_{signal}"] = m.macd_diff()
    return result


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    return AverageTrueRange(high=high, low=low, close=close, window=length).average_true_range()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.DataFrame:
    result = pd.DataFrame(index=high.index)
    result[f"ADX_{length}"] = ADXIndicator(high=high, low=low, close=close, window=length).adx()
    return result


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical_price = (high + low + close) / 3.0
    return (typical_price * volume).cumsum() / volume.cumsum()


def cdl_pattern(open_: pd.Series, high: pd.Series, low: pd.Series,
                close: pd.Series, name: str = "all") -> pd.Series:
    """
    Detects all supported candlestick patterns and returns the strongest signal
    found on each bar as an integer:
      Positive = bullish signal (long)
      Negative = bearish signal (short)
      Zero     = no pattern detected

    Magnitude encodes pattern strength (6=strongest, 2=weakest).
    checklist.py maps these magnitudes to score points.
    All detection is vectorized — shift() operations only, no Python loops.
    """

    # ── Precompute reusable values ─────────────────────────────────────────
    body        = (close - open_).abs()
    total_range = (high - low).replace(0, np.nan)
    candle_mid  = (open_ + close) / 2.0
    body_top    = open_.combine(close, max)
    body_bot    = open_.combine(close, min)
    lower_wick  = body_bot - low
    upper_wick  = high - body_top

    curr_bullish = close > open_
    curr_bearish = close < open_

    prev_open    = open_.shift(1)
    prev_close   = close.shift(1)
    prev_high    = high.shift(1)
    prev_low     = low.shift(1)
    prev_body    = body.shift(1)
    prev_mid     = candle_mid.shift(1)
    prev_bullish = prev_close > prev_open
    prev_bearish = prev_close < prev_open

    prev2_open    = open_.shift(2)
    prev2_close   = close.shift(2)
    prev2_bullish = prev2_close > prev2_open
    prev2_bearish = prev2_close < prev2_open
    prev2_body    = body.shift(2)

    # ══════════════════════════════════════════════════════════════════════
    # BULLISH PATTERNS
    # ══════════════════════════════════════════════════════════════════════

    # +6 Bullish Engulfing — strongest reversal signal
    bull_engulf = (
        prev_bearish & curr_bullish &
        (open_ < prev_close) &
        (close > prev_open)
    )

    # +5 Morning Star — reliable 3-candle reversal
    # Bar-2: large red | Bar-1: small indecision | Bar-0: strong green
    morning_star = (
        prev2_bearish &
        (prev_body <= prev2_body * 0.3) &
        curr_bullish &
        (close > (prev2_open + prev2_close) / 2)
    )

    # +5 Bullish Marubozu — strong conviction, almost no wicks
    bull_marubozu = (
        curr_bullish &
        (body >= total_range * 0.90)
    )

    # +4 Hammer — rejection of lows, buyers stepped in
    # Small body at top, lower wick 2x body, tiny upper wick
    hammer = (
        prev_bearish & curr_bullish &
        (lower_wick >= body * 2.0) &
        (upper_wick <= body * 0.1)
    )

    # +3 Piercing Line — partial engulfing, still valid
    # Opens below prev low, closes above prev midpoint but not full engulf
    piercing = (
        prev_bearish & curr_bullish &
        (open_ < prev_low) &
        (close > prev_mid) &
        (close < prev_open)
    )

    # +2 Bullish Harami — weakest, just signals selling is pausing
    # Small green inside large previous red
    bull_harami = (
        prev_bearish & curr_bullish &
        (open_ > prev_close) &
        (close < prev_open) &
        (body <= prev_body * 0.5)
    )

    # ══════════════════════════════════════════════════════════════════════
    # BEARISH PATTERNS
    # SHORT SELLING currently disabled (ENABLE_SHORT_SELLING=False in config)
    # Patterns detected and stored — will activate when shorts are enabled
    # ══════════════════════════════════════════════════════════════════════

    # -6 Bearish Engulfing
    bear_engulf = (
        prev_bullish & curr_bearish &
        (open_ > prev_close) &
        (close < prev_open)
    )

    # -5 Evening Star — 3-candle top reversal
    evening_star = (
        prev2_bullish &
        (prev_body <= prev2_body * 0.3) &
        curr_bearish &
        (close < (prev2_open + prev2_close) / 2)
    )

    # -5 Bearish Marubozu
    bear_marubozu = (
        curr_bearish &
        (body >= total_range * 0.90)
    )

    # -4 Shooting Star — rejection of highs
    shooting_star = (
        prev_bullish & curr_bearish &
        (upper_wick >= body * 2.0) &
        (lower_wick <= body * 0.1)
    )

    # -3 Dark Cloud Cover
    dark_cloud = (
        prev_bullish & curr_bearish &
        (open_ > prev_high) &
        (close < prev_mid) &
        (close > prev_close)
    )

    # -2 Bearish Harami
    bear_harami = (
        prev_bullish & curr_bearish &
        (open_ < prev_close) &
        (close > prev_open) &
        (body <= prev_body * 0.5)
    )

    # ══════════════════════════════════════════════════════════════════════
    # COMBINE — strongest signal wins per bar
    # Bullish applied last so it overrides bearish on same bar
    # ══════════════════════════════════════════════════════════════════════
    result = pd.Series(0, index=close.index, dtype=float)

    # Bearish first (weaker priority)
    result[bear_harami]   = -2
    result[dark_cloud]    = -3
    result[shooting_star] = -4
    result[bear_marubozu] = -5
    result[evening_star]  = -5
    result[bear_engulf]   = -6

    # Bullish second (takes priority over bearish)
    result[bull_harami]   =  2
    result[piercing]      =  3
    result[hammer]        =  4
    result[bull_marubozu] =  5
    result[morning_star]  =  5
    result[bull_engulf]   =  6

    return result
