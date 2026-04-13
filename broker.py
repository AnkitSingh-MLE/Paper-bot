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
    """Janitor: Closes ONLY intraday positions at 3:50 PM. Protects swing trades."""
    try:
        # Get open swing symbols from trades.csv
        csv_path = os.path.join(BASE_DIR, "trades.csv")
        swing_symbols = set()
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            swing_open = df[(df["result"] == "open") & (df["timeframe"] == "swing")]
            swing_symbols = set(swing_open["symbol"].tolist())
            if swing_symbols:
                log.info(f"JANITOR: Protecting swing positions: {swing_symbols}")

        # Close only non-swing positions
        positions = trading_client.get_all_positions()
        closed, skipped = [], []
        for p in positions:
            if p.symbol in swing_symbols:
                skipped.append(p.symbol)
            else:
                try:
                    trading_client.close_position(p.symbol)
                    closed.append(p.symbol)
                except Exception as e:
                    log.error(f"JANITOR: Failed to close {p.symbol}: {e}")

        # Cancel open orders for non-swing symbols only
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            open_orders = trading_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
            for o in open_orders:
                if o.symbol not in swing_symbols:
                    try:
                        trading_client.cancel_order_by_id(o.id)
                    except Exception:
                        pass
        except Exception as e:
            log.warning(f"JANITOR: Order cancel failed: {e}")

        log.info(f"JANITOR: Closed intraday: {closed} | Protected swing: {skipped}")

    except Exception as e:
        log.error(f"Janitor failed: {e}")
        try:
            trading_client.close_all_positions(cancel_orders=True)
            log.warning("JANITOR: Fallback — closed all positions")
        except Exception as e2:
            log.error(f"Janitor fallback failed: {e2}")

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
