"""
execution.py
────────────
execute_swing_trade    — daily bars, bracket order, DAY
execute_intraday_trade — 5-min bars, bracket order, DAY (auto-close at 4 PM)
Daily intraday cap: 5 trades (account > $25k, PDT does not apply).
"""

import math
import logging
import config
from broker import get_open_positions, trading_client
from logger import log_trade, get_daily_intraday_count
from checklist import calculate_atr_levels

log = logging.getLogger(__name__)

MAX_INTRADAY_TRADES = 5

def _position_size_calc(entry: float) -> int:
    qty = math.floor(config.MAX_POSITION_SIZE / entry)
    return max(1, qty)

def _pre_trade_guards(symbol: str, entry: float) -> tuple[bool, int]:
    try:
        positions = get_open_positions()
    except Exception as e:
        log.error(f"Could not fetch positions: {e}")
        return False, 0
    if len(positions) >= config.MAX_OPEN_POSITIONS:
        log.info(f"GUARD [{symbol}]: max positions reached")
        return False, 0
    deployed = sum(float(p.market_value) for p in positions)
    if deployed + config.MAX_POSITION_SIZE > config.MAX_DEPLOYED_CAPITAL:
        log.info(f"GUARD [{symbol}]: capital limit reached")
        return False, 0
    return True, _position_size_calc(entry)

def _intraday_cap_guard(symbol: str) -> bool:
    count = get_daily_intraday_count()
    if count >= MAX_INTRADAY_TRADES:
        log.info(f"GUARD [{symbol}]: daily intraday cap hit ({count}/{MAX_INTRADAY_TRADES})")
        return False
    return True

def execute_swing_trade(symbol: str, latest: dict) -> bool:
    try:
        entry = float(latest.get('close', 0))
        atr   = float(latest.get('atr', 0.1))
        score = int(latest.get('score', 0))
        ok, qty = _pre_trade_guards(symbol, entry)
        if not ok or qty < 1: return False
        stop, target = calculate_atr_levels(entry, atr, strategy="swing", is_short=False)
        rrr = (target - entry) / (entry - stop) if (entry - stop) > 0 else 0.0
        if rrr < config.MIN_RRR:
            log.info(f"SKIP [{symbol}]: RRR {rrr:.2f} < {config.MIN_RRR}")
            return False
        from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        trading_client.submit_order(MarketOrderRequest(
            symbol=symbol, side=OrderSide.BUY, qty=qty,
            time_in_force=TimeInForce.DAY, order_class="bracket",
            take_profit=TakeProfitRequest(limit_price=target),
            stop_loss=StopLossRequest(stop_price=stop),
        ))
        log.info(f"SWING LONG [{symbol}]: qty={qty} entry=${entry:.2f} stop=${stop:.2f} target=${target:.2f} RRR={rrr:.2f} score={score}")
        log_trade(symbol=symbol, strategy="swing_long", entry=entry,
                  target=target, stop=stop, qty=qty, rrr=rrr,
                  score=score, atr=atr, breakdown=latest)
        return True
    except Exception as e:
        log.error(f"Swing execution failed [{symbol}]: {e}")
        return False

def execute_intraday_trade(symbol: str, latest: dict, is_short: bool = False) -> bool:
    try:
        if not _intraday_cap_guard(symbol): return False
        entry = float(latest.get('close', 0))
        atr   = float(latest.get('atr', 0.1))
        score = int(latest.get('score', 0))
        ok, qty = _pre_trade_guards(symbol, entry)
        if not ok or qty < 1: return False
        stop, target = calculate_atr_levels(entry, atr, strategy="intraday", is_short=is_short)
        if is_short:
            rrr = (entry - target) / (stop - entry) if (stop - entry) > 0 else 0.0
        else:
            rrr = (target - entry) / (entry - stop) if (entry - stop) > 0 else 0.0
        if rrr < config.MIN_RRR:
            log.info(f"SKIP [{symbol}]: RRR {rrr:.2f} < {config.MIN_RRR}")
            return False
        from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        side     = OrderSide.SELL if is_short else OrderSide.BUY
        strategy = "intraday_short" if is_short else "intraday_long"
        label    = "SHORT" if is_short else "LONG"
        trading_client.submit_order(MarketOrderRequest(
            symbol=symbol, side=side, qty=qty,
            time_in_force=TimeInForce.DAY, order_class="bracket",
            take_profit=TakeProfitRequest(limit_price=target),
            stop_loss=StopLossRequest(stop_price=stop),
        ))
        log.info(f"INTRADAY {label} [{symbol}]: qty={qty} entry=${entry:.2f} stop=${stop:.2f} target=${target:.2f} RRR={rrr:.2f} score={score}")
        log_trade(symbol=symbol, strategy=strategy, entry=entry,
                  target=target, stop=stop, qty=qty, rrr=rrr,
                  score=score, atr=atr, breakdown=latest)
        return True
    except Exception as e:
        log.error(f"Intraday execution failed [{symbol}]: {e}")
        return False
