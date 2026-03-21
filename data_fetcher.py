import logging
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Optional
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from broker import data_client

log = logging.getLogger(__name__)


def get_daily_bars(symbol: str, lookback_days: int = 250) -> Optional[pd.DataFrame]:
    """
    Fetches daily OHLCV bars for swing analysis.
    Returns a clean DataFrame sorted by timestamp, or None on failure.
    """
    try:
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days + 10)  # buffer for weekends/holidays

        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            limit=lookback_days,
            feed="iex",
        )
        bars = data_client.get_stock_bars(req)
        df   = bars.df

        if df.empty:
            return None

        # Flatten multi-index if present
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")

        df = df.rename(columns=str.lower).sort_index()
        return df

    except Exception as e:
        log.error(f"{symbol} daily bars failed: {e}")
        return None


def get_intraday_bars(symbol: str, lookback_bars: int = 78) -> Optional[pd.DataFrame]:
    """
    Fetches 5-minute OHLCV bars for intraday analysis.
    78 bars ≈ one full trading day at 5-min intervals.
    """
    try:
        end   = datetime.now(timezone.utc)
        start = end - timedelta(hours=8)

        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
            start=start,
            end=end,
            limit=lookback_bars,
            feed="iex",
        )
        bars = data_client.get_stock_bars(req)
        df   = bars.df

        if df.empty:
            return None

        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")

        df = df.rename(columns=str.lower).sort_index()
        return df

    except Exception as e:
        log.error(f"{symbol} intraday bars failed: {e}")
        return None