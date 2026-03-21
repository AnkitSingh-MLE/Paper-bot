"""
Varsity Bot — Paper Trading v7
────────────────────────────────
IMPORTANT: This file sets timezone to America/New_York on startup.
           Previous issue was bot running on London time — fixed here.

Features enabled for paper trading:
  - Swing long (EOD 15:30 only, best score first)
  - Intraday long + short (full day 10:31-15:50, top 5 per day)
  - Short selling enabled
  - No PDT restrictions on paper
  - Capital limit $10,000
"""

import datetime
import logging
import logging.handlers
import os
import subprocess
import time
import sys
import yfinance as yf

from broker   import is_market_open, close_all_positions, close_intraday_only, get_account, cancel_stale_gtc_orders
from universe import get_liquid_universe, check_vix_safe
from scanner  import scan_swing, scan_intraday, close_stale_swing_positions
from logger   import get_daily_pnl
import config

# ── TIMEZONE FIX — Must be America/New_York (ET) ──────────────────────────────
# This prevents the London-time bug where scans fire at wrong times
os.environ['TZ'] = 'America/New_York'
try:
    # Works on Linux (GCP VM)
    subprocess.run(['sudo', 'timedatectl', 'set-timezone', 'America/New_York'],
                   capture_output=True, timeout=5)
except Exception:
    pass  # Non-critical — TZ env var above handles Python datetime

# ── Logging Setup ─────────────────────────────────────────────────────────────
_file_handler = logging.handlers.RotatingFileHandler(
    "bot.log",
    maxBytes=config.LOG_MAX_BYTES,
    backupCount=config.LOG_BACKUP_COUNT,
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), _file_handler],
)
log = logging.getLogger("main")


def validate_startup():
    """Validates config and refuses to start if PAPER is not True."""
    if not config.PAPER:
        log.critical("PAPER_TRADING is not True — refusing to start on live account. Set PAPER_TRADING=true in .env")
        sys.exit(1)

    if not config.API_KEY or not config.SECRET_KEY:
        log.critical("API keys missing — check .env file. Exiting.")
        sys.exit(1)

    acct = get_account()
    if not acct:
        log.critical("Cannot reach Alpaca. Check keys and network. Exiting.")
        sys.exit(1)

    import pytz
    et_now = datetime.datetime.now(pytz.timezone('America/New_York'))
    log.info("=" * 60)
    log.info(f"  Varsity Bot  |  Mode: PAPER 📄")
    log.info(f"  ET Time:      {et_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    log.info(f"  Equity:       ${acct['equity']:,.2f}")
    log.info(f"  Cash:         ${acct['cash']:,.2f}")
    log.info(f"  Buying Power: ${acct['buying_power']:,.2f}")
    log.info(f"  Daytrades:    {acct['daytrade_count']}/3 (no limit on paper)")
    log.info(f"  Swing scans:  {config.SWING_SCAN_TIMES} ET")
    log.info(f"  Intraday:     {'ON' if config.INTRADAY_ENABLED else 'OFF'} | Max {config.MAX_INTRADAY_TRADES} trades/day")
    log.info(f"  Short selling: {'ON' if config.ENABLE_SHORT_SELLING else 'OFF'}")
    log.info(f"  Capital limit: ${config.MAX_DEPLOYED_CAPITAL:,.0f}")
    log.info(f"  Max hold:     {config.SWING_MAX_HOLD_DAYS} trading days")
    log.info("=" * 60)


def daily_loss_exceeded() -> bool:
    acct = get_account()
    if not acct:
        return False
    equity_now  = acct.get("equity", 0)
    last_equity = acct.get("last_equity", equity_now)
    daily_pnl   = equity_now - last_equity
    threshold   = config.TOTAL_CAPITAL * config.DAILY_LOSS_LIMIT
    if daily_pnl < -threshold:
        log.warning(
            f"KILL SWITCH: equity ${equity_now:.2f} | "
            f"daily P&L ${daily_pnl:.2f} | "
            f"limit -${threshold:.2f} — halting trading."
        )
        return True
    return False


def is_swing_scan_window(now: datetime.time, scanned_windows: set):
    for h, m in config.SWING_SCAN_TIMES:
        window_key = f"{h}:{m:02d}"
        if window_key in scanned_windows:
            continue
        scheduled  = datetime.time(h, m)
        window_end = (datetime.datetime.combine(datetime.date.today(), scheduled)
                      + datetime.timedelta(minutes=5)).time()
        if scheduled <= now < window_end:
            return True, window_key
    return False, None


def run():
    validate_startup()
    scanned_swing_windows: set = set()
    today = datetime.date.today()
    log.info("Waiting for market open...")

    while True:
        try:
            if datetime.date.today() != today:
                today = datetime.date.today()
                scanned_swing_windows = set()
                log.info(f"New trading day: {today}")

            if not is_market_open():
                time.sleep(60)
                continue

            now = datetime.datetime.now().time()

            # ── EOD flush ─────────────────────────────────────────────────────
            eod_h, eod_m = config.EOD_CLOSE_TIME
            if now >= datetime.time(eod_h, eod_m):
                close_intraday_only()
                log.info("EOD flush complete. Sleeping 1 hour.")
                time.sleep(3600)
                continue

            # ── Daily kill switch ─────────────────────────────────────────────
            if daily_loss_exceeded():
                close_all_positions()
                time.sleep(3600)
                continue

            # ── Stale position and GTC cleanup ────────────────────────────────
            if now < datetime.time(9, 35):
                close_stale_swing_positions()
                cancel_stale_gtc_orders()

            # ── Universe & VIX ────────────────────────────────────────────────
            symbols = get_liquid_universe()
            if not symbols:
                log.warning("Empty universe — retrying in 5 min.")
                time.sleep(300)
                continue

            try:
                current_vix = yf.Ticker("^VIX").fast_info["last_price"]
            except Exception as e:
                log.warning(f"Failed to fetch VIX: {e}, using 18.0 as fallback")
                current_vix = 18.0
            if not check_vix_safe(current_vix):
                time.sleep(300)
                continue

            # ── Swing scan windows ────────────────────────────────────────────
            # 11:30 and 13:30 = scan only (log signals, no orders)
            # 15:30 EOD = place orders
            in_window, window_key = is_swing_scan_window(now, scanned_swing_windows)
            if in_window:
                label = {"11:30": "MORNING", "13:30": "MIDDAY", "15:30": "EOD"}.get(window_key, window_key)
                place_orders = (window_key == "15:30")
                log.info(f"Running {label} swing scan on {len(symbols)} symbols {'(orders enabled)' if place_orders else '(scan only)'}...")
                placed = scan_swing(symbols, place_orders=place_orders)
                log.info(f"Swing scan complete — {placed} orders placed.")
                scanned_swing_windows.add(window_key)

            # ── Intraday scan — full day 10:31-15:50, top 5 combined ──────────
            start_h, start_m = config.INTRADAY_START_TIME
            if now >= datetime.time(start_h, start_m) and config.INTRADAY_ENABLED:
                placed = scan_intraday(symbols)
                if placed:
                    log.info(f"Intraday scan — {placed} orders placed.")

            time.sleep(config.SCAN_INTERVAL_SEC)

        except KeyboardInterrupt:
            log.info("Manual stop — closing intraday positions and exiting.")
            close_intraday_only()
            sys.exit(0)

        except Exception as e:
            log.error(f"Main loop error: {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    run()
