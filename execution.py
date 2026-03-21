"""
execution.py v7 — Paper Trading
────────────────────────────────
Swing:    GTC, whole shares, $200 base sizing
Intraday: DAY, fractional OK, $1000 base sizing
Both:     Capital limit $10k, cash check, RRR gate
"""

import logging
import math
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest,
    TakeProfitRequest, StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from broker import trading_client, already_in_position, get_open_positions
from checklist import calculate_rrr, calculate_short_rrr, score_based_position_size, intraday_position_size
import config

log = logging.getLogger(__name__)


def _position_size_gtc(entry: float, stop: float, score: int) -> float:
    """Swing GTC — whole shares only, minimum 1."""
    dollar_size    = score_based_position_size(score)
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0: return 0.0
    risk_shares   = (config.SWING_CAPITAL * config.MAX_RISK_PER_TRADE) / risk_per_share
    dollar_shares = dollar_size / entry
    return max(1.0, math.floor(min(risk_shares, dollar_shares)))


def _position_size_day(entry: float, stop: float, score: int) -> float:
    """Intraday DAY — fractional allowed, $1000 base."""
    dollar_size    = intraday_position_size(score)
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0: return 0.0
    risk_shares   = (config.INTRADAY_CAPITAL * config.MAX_RISK_PER_TRADE) / risk_per_share
    dollar_shares = dollar_size / entry
    return round(min(risk_shares, dollar_shares), 6)


def _pre_trade_guards(symbol: str, entry: float, stop: float, target: float,
                      is_short: bool, strategy: str, score: int) -> tuple[bool, float, float]:
    if already_in_position(symbol):
        log.info(f"{symbol}: already in position — skipped.")
        return False, 0, 0

    if len(get_open_positions()) >= config.MAX_OPEN_POSITIONS:
        log.info(f"Max positions reached — skipped {symbol}.")
        return False, 0, 0

    if is_short and not config.ENABLE_SHORT_SELLING:
        return False, 0, 0

    if is_short:
        try:
            asset = trading_client.get_asset(symbol)
            if not asset.shortable:
                log.info(f"{symbol}: not shortable — skipped.")
                return False, 0, 0
        except Exception as e:
            log.error(f"{symbol}: asset check failed — {e}")
            return False, 0, 0

    rrr = calculate_short_rrr(entry, target, stop) if is_short else calculate_rrr(entry, target, stop)
    if rrr < config.MIN_RRR:
        log.info(f"{symbol}: RRR {rrr:.2f} < {config.MIN_RRR} — rejected.")
        return False, 0, 0

    qty = _position_size_day(entry, stop, score) if strategy == "intraday" else _position_size_gtc(entry, stop, score)

    if qty <= 0:
        log.info(f"{symbol}: qty is 0 — skipped.")
        return False, 0, 0

    if qty * entry < 1.0:
        log.info(f"{symbol}: order value too small — skipped.")
        return False, 0, 0

    # Capital limit check
    from broker import get_account
    current_positions = get_open_positions()
    deployed    = sum(float(p.market_value) for p in current_positions)
    order_value = qty * entry
    if deployed + order_value > config.MAX_DEPLOYED_CAPITAL:
        log.warning(f"{symbol}: deployed ${deployed:.0f} + ${order_value:.0f} exceeds limit ${config.MAX_DEPLOYED_CAPITAL:.0f} — skipped.")
        return False, 0, 0

    # Cash check
    acct = get_account()
    if order_value > acct.get("cash", 0):
        log.warning(f"{symbol}: order ${order_value:.0f} exceeds cash ${acct.get('cash',0):.0f} — skipped.")
        return False, 0, 0

    alloc = intraday_position_size(score) if strategy == "intraday" else score_based_position_size(score)
    log.info(f"{symbol}: score={score} → alloc=${alloc:.0f} | qty={qty} | value=${order_value:.2f} | deployed=${deployed:.0f}/${config.MAX_DEPLOYED_CAPITAL:.0f}")
    return True, qty, rrr


def place_bracket_order(
    symbol: str, entry: float, stop: float, target: float,
    strategy: str = "intraday", is_short: bool = False, score: int = 0,
) -> bool:
    """Intraday DAY bracket order. Fractional shares allowed."""
    direction = "SHORT" if is_short else "LONG"
    ok, qty, rrr = _pre_trade_guards(symbol, entry, stop, target, is_short, strategy, score)
    if not ok: return False
    try:
        order = trading_client.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty,
            side=OrderSide.SELL if is_short else OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(target, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop, 2)),
        ))
        alloc = intraday_position_size(score)
        log.info(f"INTRADAY {direction} → {symbol} | score={score} | alloc=${alloc:.0f} | qty={qty} | ≈${entry:.2f} | stop=${stop:.2f} | tp=${target:.2f} | RRR={rrr:.2f} | {order.id}")
        return True
    except Exception as e:
        log.error(f"{symbol} intraday order failed: {e}")
        return False


def place_swing_order(
    symbol: str, entry: float, stop: float, target: float, score: int = 0,
) -> bool:
    """Swing GTC limit order. Whole shares only. Long only."""
    ok, qty, rrr = _pre_trade_guards(symbol, entry, stop, target, False, "swing", score)
    if not ok: return False
    try:
        order = trading_client.submit_order(LimitOrderRequest(
            symbol=symbol, qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            limit_price=round(entry, 2),
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(target, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop, 2)),
        ))
        log.info(f"SWING LONG → {symbol} | score={score} | alloc=${score_based_position_size(score):.0f} | qty={qty} shares | limit=${entry:.2f} | stop=${stop:.2f} | tp=${target:.2f} | RRR={rrr:.2f} | {order.id}")
        return True
    except Exception as e:
        log.error(f"{symbol} swing order failed: {e}")
        return False
