import logging
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Optional
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from broker import data_client

log = logging.getLogger(__name__)

def get_delayed_end_time():
    """Adjusts for the 15-minute free-tier data delay."""
    return datetime.now(timezone.utc) - timedelta(minutes=16)

def get_daily_bars(symbol: str, lookback_days: int = 400) -> Optional[pd.DataFrame]:
    try:
        end = get_delayed_end_time()
        start = end - timedelta(days=lookback_days + 10)
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed="iex"
        )
        bars = data_client.get_stock_bars(req)
        df = bars.df
        if df.empty: return None
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")
        return df.rename(columns=str.lower).sort_index()
    except Exception as e:
        log.error(f"{symbol} daily bars failed: {e}")
        return None

def get_intraday_bars(symbol: str, lookback_bars: int = 78) -> Optional[pd.DataFrame]:
    try:
        end = get_delayed_end_time()
        start = end - timedelta(hours=8)
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
            start=start,
            end=end,
            feed="iex"
        )
        bars = data_client.get_stock_bars(req)
        df = bars.df
        if df.empty: return None
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")
        return df.rename(columns=str.lower).sort_index()
    except Exception as e:
        log.error(f"{symbol} intraday failed: {e}")
        return None
