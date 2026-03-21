"""
scanner.py v7 — Paper Trading
───────────────────────────────
scan_swing():     Phase 1 collect all, Phase 2 sort by score, Phase 3 place best at 15:30 only
scan_intraday():  Collect long + short combined, sort by score, place top 5 per day
"""
import logging
from datetime import date, timedelta
from typing import Optional

from data_fetcher import get_daily_bars, get_intraday_bars
from indicators   import calculate_swing_indicators, calculate_intraday_indicators
from checklist    import (
    score_varsity_swing, score_intraday_long, score_intraday_short,
    calculate_atr_levels, calculate_rrr, calculate_short_rrr,
)
from execution import place_bracket_order, place_swing_order
from logger    import log_trade, get_swing_entry_dates, get_daily_intraday_count
from broker    import get_open_positions, trading_client, check_earnings_soon
import config

log = logging.getLogger(__name__)


def _extract_latest(df, min_rows=21):
    if df is None or len(df) < min_rows:
        return None
    row = df.iloc[-1]
    for col in ["close", "rsi", "atr"]:
        if col in row.index and row[col] != row[col]:
            return None
    return row.to_dict()


def close_stale_swing_positions():
    cutoff      = date.today() - timedelta(days=config.SWING_MAX_HOLD_DAYS)
    entry_dates = get_swing_entry_dates()
    positions   = get_open_positions()
    for position in positions:
        sym = position.symbol
        if sym not in entry_dates:
            continue
        if entry_dates[sym] <= cutoff:
            try:
                trading_client.close_position(sym)
                log.info(f"STALE SWING CLOSED: {sym} | held {(date.today()-entry_dates[sym]).days} days")
            except Exception as e:
                log.error(f"Failed to close stale position {sym}: {e}")


def scan_swing(symbols: list, place_orders: bool = True) -> int:
    """
    Phase 1: Scan ALL symbols, collect ALL passing signals.
    Phase 2: Sort by score descending — best signals first.
    Phase 3: Place only top scoring at EOD (15:30). Log only at 11:30 and 13:30.
    """
    signals = []
    for sym in symbols:
        try:
            df = get_daily_bars(sym)
            if df is None: continue
            df     = calculate_swing_indicators(df)
            latest = _extract_latest(df, min_rows=30)
            if latest is None: continue
            passed, score, notes, breakdown = score_varsity_swing(latest)
            if not passed: continue
            entry = latest["close"]
            atr   = latest["atr"]
            stop, target = calculate_atr_levels(entry, atr, strategy="swing", is_short=False)
            rrr = calculate_rrr(entry, target, stop)
            if rrr < config.MIN_RRR: continue
            if check_earnings_soon(sym): continue
            signals.append({
                "sym": sym, "score": score, "entry": entry,
                "stop": stop, "target": target, "atr": atr,
                "rrr": rrr, "notes": notes, "breakdown": breakdown,
                "latest": latest,
            })
        except Exception as e:
            log.error(f"Swing scan error {sym}: {e}")

    if not signals:
        log.info("Swing scan: no signals found.")
        return 0

    signals.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"Swing scan: {len(signals)} signals | ranked: {[(s['sym'], s['score']) for s in signals]}")

    if not place_orders:
        log.info("Scan-only mode — signals logged, no orders placed.")
        return 0

    open_count      = len(get_open_positions())
    slots_available = config.MAX_OPEN_POSITIONS - open_count
    if slots_available <= 0:
        log.info("Max positions already held — no new swing orders.")
        return 0

    placed = 0
    for sig in signals[:slots_available]:
        sym = sig["sym"]
        try:
            log.info(
                f"SWING SIGNAL → {sym} | score={sig['score']} | "
                f"${sig['entry']:.2f} | EMA200=${sig['latest'].get('ema_200',0):.2f} | "
                f"pattern={sig['breakdown'].get('pattern','none')} | "
                f"vol_ratio={sig['breakdown'].get('vol_ratio',0):.2f} | "
                f"RSI={sig['latest']['rsi']:.0f} | RRR={sig['rrr']:.2f} | {sig['notes']}"
            )
            submitted = place_swing_order(sym, sig["entry"], sig["stop"], sig["target"], score=sig["score"])
            if submitted:
                log_trade(
                    symbol=sym, strategy="swing_long",
                    entry=sig["entry"], target=sig["target"], stop=sig["stop"],
                    qty=0, rrr=sig["rrr"], score=sig["score"],
                    atr=sig["atr"], breakdown=sig["breakdown"],
                )
                placed += 1
        except Exception as e:
            log.error(f"Swing order error {sym}: {e}")

    return placed


def scan_intraday(symbols: list) -> int:
    """
    Collects long AND short signals from all symbols.
    Combines into single ranked list by score.
    Places top MAX_INTRADAY_TRADES (5) per day total.
    One direction per symbol per bar (VWAP position determines direction).
    """
    trades_today = get_daily_intraday_count()
    if trades_today >= config.MAX_INTRADAY_TRADES:
        log.info(f"Intraday limit reached: {trades_today}/{config.MAX_INTRADAY_TRADES} trades today.")
        return 0

    slots_left = config.MAX_INTRADAY_TRADES - trades_today

    signals = []
    for sym in symbols:
        try:
            df = get_intraday_bars(sym)
            if df is None or len(df) < 21: continue
            df     = calculate_intraday_indicators(df)
            latest = _extract_latest(df, min_rows=21)
            if latest is None: continue
            vwap = latest.get("vwap")
            if vwap is None or vwap != vwap: continue
            entry = latest["close"]
            atr   = latest["atr"]
            rsi   = latest.get("rsi", 50)

            # Try long first (price above VWAP)
            long_passed, long_score, long_notes, long_bd = score_intraday_long(latest)
            if long_passed:
                stop, target = calculate_atr_levels(entry, atr, "intraday", is_short=False)
                rrr = calculate_rrr(entry, target, stop)
                if rrr >= config.MIN_RRR:
                    signals.append({
                        "sym": sym, "score": long_score, "direction": "long",
                        "entry": entry, "stop": stop, "target": target,
                        "atr": atr, "rrr": rrr, "rsi": rsi, "vwap": vwap,
                        "notes": long_notes, "breakdown": long_bd,
                    })
                    continue  # one direction per symbol

            # Try short (price below VWAP)
            short_passed, short_score, short_notes, short_bd = score_intraday_short(latest)
            if short_passed:
                stop, target = calculate_atr_levels(entry, atr, "intraday", is_short=True)
                rrr = calculate_short_rrr(entry, target, stop)
                if rrr >= config.MIN_RRR:
                    signals.append({
                        "sym": sym, "score": short_score, "direction": "short",
                        "entry": entry, "stop": stop, "target": target,
                        "atr": atr, "rrr": rrr, "rsi": rsi, "vwap": vwap,
                        "notes": short_notes, "breakdown": short_bd,
                    })

        except Exception as e:
            log.error(f"Intraday scan error {sym}: {e}")

    if not signals:
        return 0

    signals.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"Intraday scan: {len(signals)} signals | top: {[(s['sym'], s['direction'], s['score']) for s in signals[:5]]}")

    placed = 0
    for sig in signals[:slots_left]:
        sym      = sig["sym"]
        is_short = sig["direction"] == "short"
        strategy = f"intraday_{sig['direction']}"
        try:
            log.info(
                f"INTRADAY {sig['direction'].upper()} → {sym} | score={sig['score']} | "
                f"${sig['entry']:.2f} | VWAP=${sig['vwap']:.2f} | RSI={sig['rsi']:.0f} | "
                f"RRR={sig['rrr']:.2f} | {sig['notes']}"
            )
            submitted = place_bracket_order(
                sym, sig["entry"], sig["stop"], sig["target"],
                strategy="intraday", is_short=is_short, score=sig["score"],
            )
            if submitted:
                log_trade(
                    symbol=sym, strategy=strategy,
                    entry=sig["entry"], target=sig["target"], stop=sig["stop"],
                    qty=0, rrr=sig["rrr"], score=sig["score"],
                    atr=sig["atr"], breakdown=sig["breakdown"],
                )
                placed += 1
        except Exception as e:
            log.error(f"Intraday order error {sym}: {e}")

    return placed
