import logging
import os
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
import config
import pandas as pd
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# Base directory — always relative to this file, not cwd
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Initialize both clients
trading_client = TradingClient(config.API_KEY, config.SECRET_KEY, paper=config.PAPER)
data_client    = StockHistoricalDataClient(config.API_KEY, config.SECRET_KEY)

def is_market_open():
    return trading_client.get_clock().is_open

def get_open_positions():
    return trading_client.get_all_positions()

def force_close_intraday():
    """Janitor: Force-closes ALL positions and cancels all orders at EOD."""
    try:
        trading_client.close_all_positions(cancel_orders=True)
        log.info("JANITOR: All positions closed and orders cancelled.")
    except Exception as e:
        log.error(f"Janitor failed: {e}")

def close_stale_swing_trades():
    """Reaper: Closes swing trades older than SWING_MAX_HOLD_DAYS."""
    try:
        csv_path = os.path.join(BASE_DIR, "trades.csv")
        if not os.path.exists(csv_path):
            log.warning(f"REAPER: trades.csv not found at {csv_path}")
            return
        df = pd.read_csv(csv_path)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        cutoff = datetime.now() - timedelta(days=config.SWING_MAX_HOLD_DAYS)
        stale = df[
            (df['result'] == 'open') &
            (df['timeframe'] == 'swing') &
            (df['timestamp'] < cutoff)
        ]
        if stale.empty:
            log.info("REAPER: No stale swing trades found.")
            return
        for _, row in stale.iterrows():
            try:
                trading_client.close_position(row['symbol'])
                log.info(f"REAPER: Closed stale swing {row['symbol']} (held since {row['timestamp'].date()})")
            except Exception as e:
                log.error(f"REAPER: Failed to close {row['symbol']}: {e}")
    except Exception as e:
        log.error(f"Reaper failed: {e}")
