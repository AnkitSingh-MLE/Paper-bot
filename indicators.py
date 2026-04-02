"""
indicators.py
─────────────
Swing:    Daily bars — EMA200/50/20, ADX, ATR, RSI, MACD, candlestick patterns
Intraday: 5-min bars — ORB, VWAP, EMA9/20, ATR, RSI, volume surge

Professional intraday strategy:
  Opening Range = first 6 x 5-min bars (9:30–10:00 AM ET)
  Signals fire from 10:00 AM onward — ORB breakout or VWAP reclaim
  EMA9/20 used as trend filter (not entry trigger)
"""

import pandas_ta_compat as ta
import pandas as pd
import numpy as np


def calculate_swing_indicators(df):
    if df is None or len(df) < 200:
        return None

    df = df.copy()
    df['ema_200'] = ta.ema(df['close'], length=200)
    df['ema_20']  = ta.ema(df['close'], length=20)
    df['ema_50']  = ta.ema(df['close'], length=50)

    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx_df is not None:
        df['adx'] = adx_df['ADX_14']

    df['atr']  = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['rsi']  = ta.rsi(df['close'], length=14)

    macd_df = ta.macd(df['close'], fast=12, slow=26, signal=9)
    if macd_df is not None:
        df['macd_line']   = macd_df['MACD_12_26_9']
        df['macd_signal'] = macd_df['MACDs_12_26_9']
        df['macd_hist']   = macd_df['MACDh_12_26_9']

    df['engulfing'] = ta.cdl_pattern(df['open'], df['high'], df['low'], df['close'])
    df['vol_ratio'] = df['volume'] / df['volume'].rolling(20).mean()

    return df.dropna(subset=['ema_200', 'adx', 'atr', 'rsi', 'macd_line', 'macd_signal'])


def calculate_intraday_indicators(df: pd.DataFrame):
    if df is None or len(df) < 8:
        return None

    df = df.copy()

    df['vwap']  = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
    df['ema_9'] = ta.ema(df['close'], length=9)
    df['ema_20']= ta.ema(df['close'], length=20)
    df['atr']   = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['rsi']   = ta.rsi(df['close'], length=14)

    vol_ma = df['volume'].rolling(20, min_periods=1).mean()
    df['vol_ratio'] = df['volume'] / vol_ma.replace(0, np.nan)

    df['bar_num'] = range(len(df))
    or_high = df['high'].iloc[:6].max()
    or_low  = df['low'].iloc[:6].min()
    df['or_high']  = or_high
    df['or_low']   = or_low
    df['or_range'] = or_high - or_low

    after_or = df['bar_num'] >= 6
    df['orb_long']  = after_or & (df['close'] > df['or_high'])
    df['orb_short'] = after_or & (df['close'] < df['or_low'])

    df['orb_long_first']  = df['orb_long']  & ~df['orb_long'].shift(1).fillna(False)
    df['orb_short_first'] = df['orb_short'] & ~df['orb_short'].shift(1).fillna(False)

    prev_close = df['close'].shift(1)
    prev_vwap  = df['vwap'].shift(1)
    df['vwap_reclaim_long']  = after_or & (prev_close < prev_vwap) & (df['close'] > df['vwap'])
    df['vwap_reclaim_short'] = after_or & (prev_close > prev_vwap) & (df['close'] < df['vwap'])

    df['ema_trend_long']  = df['ema_9'] > df['ema_20']
    df['ema_trend_short'] = df['ema_9'] < df['ema_20']

    return df.dropna(subset=['ema_9', 'ema_20', 'vwap', 'atr', 'rsi'])
