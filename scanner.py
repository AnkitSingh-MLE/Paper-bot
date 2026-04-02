"""
scanner.py
──────────
Swing:    Daily bars, runs once after 3:30 PM
Intraday: 5-min bars, runs every cycle 9:30 AM-2:00 PM ET
          ORB + VWAP reclaim, long and short, 5 trades/day cap
"""

import logging
import time
import concurrent.futures
import datetime
import pytz

import data_fetcher
import indicators
import checklist
import execution

log = logging.getLogger(__name__)

MAX_WORKERS          = 4
SYMBOL_TIMEOUT_SEC   = 8
MAX_TRADES_PER_CYCLE = 3

ET = pytz.timezone("America/New_York")
INTRADAY_START = datetime.time(9, 30)
INTRADAY_END   = datetime.time(14, 0)

def _intraday_window_open() -> bool:
    now_et = datetime.datetime.now(ET).time()
    return INTRADAY_START <= now_et <= INTRADAY_END

def _process_swing_symbol(sym: str) -> dict | None:
    try:
        df = data_fetcher.get_daily_bars(sym)
        df = indicators.calculate_swing_indicators(df)
        if df is None or df.empty: return None
        latest = df.iloc[-1].to_dict()
        latest["atr"]   = float(latest.get("atr") or 0.1)
        latest["score"] = 0
        passed, score, notes, breakdown = checklist.score_varsity_swing_long(latest)
        if not passed: return None
        latest["score"] = score
        latest.update(breakdown)
        return {"sym": sym, "latest": latest, "score": score, "is_short": False}
    except Exception as e:
        log.warning(f"[{sym}] swing error: {e}")
        return None

def _process_intraday_symbol(sym: str) -> dict | None:
    try:
        df = data_fetcher.get_intraday_bars(sym)
        time.sleep(0.3)
        df = indicators.calculate_intraday_indicators(df)
        if df is None or df.empty: return None
        latest = df.iloc[-1].to_dict()
        latest["atr"]   = float(latest.get("atr") or 0.1)
        latest["score"] = 0
        passed_long, score_long, _, bd_long = checklist.score_intraday_long(latest)
        if passed_long:
            latest["score"] = score_long
            latest.update(bd_long)
            return {"sym": sym, "latest": latest, "score": score_long, "is_short": False}
        passed_short, score_short, _, bd_short = checklist.score_intraday_short(latest)
        if passed_short:
            latest["score"] = score_short
            latest.update(bd_short)
            return {"sym": sym, "latest": latest, "score": score_short, "is_short": True}
        return None
    except Exception as e:
        log.warning(f"[{sym}] intraday error: {e}")
        return None

def _run_parallel(worker_fn, symbols: list) -> list[dict]:
    signals = []
    total_timeout = SYMBOL_TIMEOUT_SEC * max(len(symbols), 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(worker_fn, sym): sym for sym in symbols}
        for future in concurrent.futures.as_completed(futures, timeout=total_timeout):
            sym = futures[future]
            try:
                result = future.result(timeout=SYMBOL_TIMEOUT_SEC)
                if result: signals.append(result)
            except concurrent.futures.TimeoutError:
                log.warning(f"[{sym}] timeout, skipping")
            except Exception as e:
                log.warning(f"[{sym}] error: {e}")
    return signals

def scan_swing(symbols: list, place_orders: bool = True) -> int:
    log.info(f"SWING SCAN: {len(symbols)} symbols")
    signals = _run_parallel(_process_swing_symbol, symbols)
    signals.sort(key=lambda x: x["score"], reverse=True)
    traded = 0
    for sig in signals:
        if traded >= MAX_TRADES_PER_CYCLE:
            log.info(f"SWING: cycle cap hit ({MAX_TRADES_PER_CYCLE})")
            break
        if place_orders:
            if execution.execute_swing_trade(sig["sym"], sig["latest"]):
                traded += 1
    log.info(f"SWING SCAN done: {len(signals)} signal(s), {traded} order(s)")
    return traded

def scan_intraday(symbols: list, place_orders: bool = True) -> int:
    if not _intraday_window_open():
        log.debug("Intraday window closed, skipping scan")
        return 0
    log.info(f"INTRADAY SCAN: {len(symbols)} symbols")
    signals = _run_parallel(_process_intraday_symbol, symbols)
    signals.sort(key=lambda x: x["score"], reverse=True)
    traded = 0
    for sig in signals:
        if traded >= MAX_TRADES_PER_CYCLE:
            log.info(f"INTRADAY: cycle cap hit ({MAX_TRADES_PER_CYCLE})")
            break
        if place_orders:
            if execution.execute_intraday_trade(sig["sym"], sig["latest"], is_short=sig["is_short"]):
                traded += 1
    directions = [(s["sym"], "S" if s["is_short"] else "L", s["score"]) for s in signals]
    log.info(f"INTRADAY SCAN done: {len(signals)} signal(s) {directions}, {traded} order(s)")
    return traded
