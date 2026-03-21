import logging
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
import config

log = logging.getLogger(__name__)

trading_client = TradingClient(config.API_KEY, config.SECRET_KEY, paper=config.PAPER)
data_client    = StockHistoricalDataClient(config.API_KEY, config.SECRET_KEY)


def is_market_open() -> bool:
    try:
        return trading_client.get_clock().is_open
    except Exception as e:
        log.error(f"Clock check failed: {e}")
        return False


def get_account() -> dict:
    try:
        acct = trading_client.get_account()
        return {
            "equity":          float(acct.equity),
            "cash":            float(acct.cash),
            "buying_power":    float(acct.buying_power),
            "daytrade_count":  int(acct.daytrade_count),
            "portfolio_value": float(acct.portfolio_value),
            "last_equity":     float(acct.last_equity),
        }
    except Exception as e:
        log.error(f"Account fetch failed: {e}")
        return {}


def get_open_positions() -> list:
    try:
        return trading_client.get_all_positions()
    except Exception as e:
        log.error(f"Positions fetch failed: {e}")
        return []


def close_all_positions():
    try:
        trading_client.close_all_positions(cancel_orders=True)
        log.info("EOD flush: all positions closed, all orders cancelled.")
    except Exception as e:
        log.error(f"EOD close failed: {e}")


def already_in_position(symbol: str) -> bool:
    return any(p.symbol == symbol for p in get_open_positions())


def close_intraday_only():
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    try:
        all_orders = trading_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
        day_cancelled = 0
        for order in all_orders:
            if "day" in str(order.time_in_force).lower():
                try:
                    trading_client.cancel_order_by_id(order.id)
                    day_cancelled += 1
                except Exception as e:
                    log.error(f"Cancel DAY order {order.id} failed: {e}")
        log.info(f"EOD flush: {day_cancelled} intraday DAY orders cancelled. GTC swing orders preserved.")
    except Exception as e:
        log.error(f"EOD intraday close failed: {e}")


def cancel_stale_gtc_orders():
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.GTC_MAX_DAYS)
    try:
        orders = trading_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
        cancelled = 0
        for order in orders:
            if "gtc" in str(order.time_in_force).lower() and order.created_at < cutoff:
                try:
                    trading_client.cancel_order_by_id(order.id)
                    cancelled += 1
                    age = (datetime.now(timezone.utc) - order.created_at).days
                    log.info(f"STALE GTC CANCELLED: {order.symbol} | placed {order.created_at.date()} | {age} days old")
                except Exception as e:
                    log.error(f"Cancel stale GTC {order.id} failed: {e}")
        log.info(f"Stale GTC cleanup: {cancelled} orders cancelled")
    except Exception as e:
        log.error(f"Stale GTC cancel failed: {e}")


def check_earnings_soon(symbol: str, days_ahead: int = 3) -> bool:
    try:
        import yfinance as yf
        from datetime import date, timedelta
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        if cal is None or cal.empty:
            return False
        today  = date.today()
        cutoff = today + timedelta(days=days_ahead)
        if 'Earnings Date' in cal.index:
            earnings_dates = cal.loc['Earnings Date']
            for ed in (earnings_dates if hasattr(earnings_dates, '__iter__') else [earnings_dates]):
                try:
                    ed_date = ed.date() if hasattr(ed, 'date') else ed
                    if today <= ed_date <= cutoff:
                        log.warning(f"{symbol}: earnings on {ed_date} — skipping")
                        return True
                except Exception:
                    pass
        return False
    except Exception:
        return False
