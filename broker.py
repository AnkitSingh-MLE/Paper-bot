import logging
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
import config
import pandas as pd
import os
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# Initialize both clients for Latest SDK
trading_client = TradingClient(config.API_KEY, config.SECRET_KEY, paper=config.PAPER)
data_client = StockHistoricalDataClient(config.API_KEY, config.SECRET_KEY)

def is_market_open():
    return trading_client.get_clock().is_open

def get_open_positions():
    return trading_client.get_all_positions()

def force_close_intraday():
    """Janitor: Closes all Day Trades at 3:50 PM ET."""
    try:
        trading_client.close_all_positions(cancel_orders=True)
        log.info("JANITOR: All intraday positions closed.")
    except Exception as e:
        log.error(f"Janitor failed: {e}")

def close_stale_swing_trades():
    """Reaper: Closes Swing trades older than 15 days."""
    try:
        if not os.path.exists("trades.csv"): return
        df = pd.read_csv("trades.csv")
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        cutoff = datetime.now() - timedelta(days=config.SWING_MAX_HOLD_DAYS)
        
        stale = df[(df['result'] == 'open') & (df['timeframe'] == 'swing') & (df['timestamp'] < cutoff)]
        for _, row in stale.iterrows():
            log.info(f"REAPER: Closing stale trade {row['symbol']}")
            trading_client.close_position(row['symbol'])
    except Exception as e:
        log.error(f"Reaper failed: {e}")
