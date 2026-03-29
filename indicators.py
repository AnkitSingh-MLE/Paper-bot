import pandas_ta as ta
import pandas as pd
import numpy as np

def calculate_swing_indicators(df):
    # Safety check: Alpaca needs at least 200 days of data for EMA 200
    if df is None or len(df) < 200:
        return None

    # Use pandas_ta to calculate Alpaca-based indicators
    df['ema_200'] = ta.ema(df['close'], length=200)
    df['ema_20'] = ta.ema(df['close'], length=20)
    df['ema_50'] = ta.ema(df['close'], length=50)
    
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx_df is not None:
        df['adx'] = adx_df['ADX_14']
    
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    
    # Remove any rows where Alpaca data is missing
    return df.dropna(subset=['ema_200', 'adx', 'atr'])
