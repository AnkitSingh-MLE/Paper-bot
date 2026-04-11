"""
scanner.py
──────────
Swing:    Daily bars, runs once after 3:30 PM — top 3 by score
Intraday: 5-min bars, accumulates signals 9:30 AM-1:00 PM ET
          At 1:00 PM executes TOP 5 by score only (patience filter)
          ORB + VWAP reclaim, long and short
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

MAX_WORKERS           = 4
SYMBOL_TIMEOUT_SEC    = 8
MAX_TRADES_PER_CYCLE  = 3   # swing cap
MAX_INTRADAY_TRADES   = 5   # intraday daily cap

ET = pytz.timezone("America/New_York")
INTRADAY_SCAN_START  = datetime.time(9, 30)   # start scanning at open
INTRADAY_SCAN_END    = datetime.time(13, 0)   # stop scanning at 1 PM
INTRADAY_EXECUTE_AT  = datetime.time(13, 0)   # execute best signals at 1 PM

# Accumulator: best signals seen across all scan cycles today
_best_signals: dict[str, dict] = {}   # sym -> best signal dict
_executed_today: set            = set()
_last_execute_date              = None


def _intraday_window_open() -> bool:
    now_et = datetime.datetime.now(ET).time()
    return INTRADAY_SCAN_START <= now_et <= INTRADAY_SCAN_END


def _is_execute_time() -> bool:
    now_et = datetime.datetime.now(ET)
    return now_et.time() >= INTRADAY_EXECUTE_AT


def _reset_if_new_day():
    global _best_signals, _executed_today, _last_execute_date
    today = datetime.datetime.now(ET).date()
    if _last_execute_date != today:
        _best_signals      = {}
        _executed_today    = set()
        _last_execute_date = today
        log.info("INTRADAY: New day — signal accumulator reset")


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
    global _best_signals, _executed_today

    _reset_if_new_day()

    if not _intraday_window_open():
        log.debug("Intraday scan window closed")
        return 0

    # ── Accumulate best signals across cycles ──
    log.info(f"INTRADAY SCAN: {len(symbols)} symbols")
    new_signals = _run_parallel(_process_intraday_symbol, symbols)

    for sig in new_signals:
        sym = sig["sym"]
        if sym not in _best_signals or sig["score"] > _best_signals[sym]["score"]:
            _best_signals[sym] = sig

    log.info(f"INTRADAY: {len(new_signals)} signals this cycle | {len(_best_signals)} unique accumulated today")

    # ── Execute at 1 PM: top 5 by score, never repeat a symbol ──
    traded = 0
    if _is_execute_time() and place_orders:
        # Get top 20 candidates by historical score
        candidates = [
            s for sym, s in _best_signals.items()
            if sym not in _executed_today
        ]
        candidates.sort(key=lambda x: x["score"], reverse=True)
        top20_syms = [s["sym"] for s in candidates[:20]]

        if top20_syms:
            log.info(f"INTRADAY EXECUTE: rescanning top {len(top20_syms)} candidates for fresh scores at 1 PM")
            fresh_signals = _run_parallel(_process_intraday_symbol, top20_syms)
            fresh_signals.sort(key=lambda x: x["score"], reverse=True)
            top5 = fresh_signals[:MAX_INTRADAY_TRADES]

            for sig in top5:
                sym = sig["sym"]
                log.info(f"EXECUTE: {sym} fresh score={sig['score']} direction={'SHORT' if sig['is_short'] else 'LONG'}")
                if execution.execute_intraday_trade(sig["sym"], sig["latest"], is_short=sig["is_short"]):
                    traded += 1
                _executed_today.add(sym)
        else:
            log.info("INTRADAY EXECUTE: no candidates at 1 PM")

    directions = [(s["sym"], "S" if s["is_short"] else "L", s["score"]) for s in new_signals]
    log.info(f"INTRADAY SCAN done: {len(new_signals)} signal(s) {directions}, {traded} order(s)")
    return traded
