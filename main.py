"""
main.py — Varsity Paper Bot
────────────────────────────
GCP micro-CPU friendly:
  • Sleeps until the next scheduled interval instead of spinning every 5 min
  • Swing scan is triggered once per day at 3:30 PM
  • Intraday scan runs every SCAN_INTERVAL_SEC but only during market hours
  • Market-closed check throttled to one wake-up per minute
"""
import datetime
import time
import logging
from broker import is_market_open, force_close_intraday, close_stale_swing_trades
import config
from universe import get_liquid_universe
from scanner import scan_swing, scan_intraday

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")

# Track whether the swing scan already ran today
_swing_scan_done_date: datetime.date | None = None
# Track whether janitors already ran today
_intraday_closed_date: datetime.date | None = None
_stale_reaped_date: datetime.date | None = None

def run():
    global _swing_scan_done_date, _intraday_closed_date, _stale_reaped_date
    log.info("STARTING PAPER BOT: $25k Swing / $25k Day (GCP micro build)")
    symbols = get_liquid_universe()
    log.info(f"Universe loaded: {len(symbols)} symbols")

    while True:
        if not is_market_open():
            log.info("Market is closed. Sleeping 60s...")
            time.sleep(60)
            continue

        now   = datetime.datetime.now()
        today = now.date()

        # ── JANITOR: stale swing positions — runs once after 3:31 PM ──
        stale_h, stale_m = config.STALE_REAPER_TIME
        if (now.hour, now.minute) >= (stale_h, stale_m) and _stale_reaped_date != today:
            log.info("REAPER: Checking for stale swing positions...")
            close_stale_swing_trades()
            _stale_reaped_date = today

        # ── JANITOR: force-close ALL intraday positions — runs once after 3:50 PM ──
        eod_h, eod_m = config.EOD_CLOSE_TIME
        if (now.hour, now.minute) >= (eod_h, eod_m) and _intraday_closed_date != today:
            log.info("JANITOR: Force-closing all intraday positions at EOD...")
            force_close_intraday()
            _intraday_closed_date = today

        # ── INTRADAY SCAN: every cycle while market is open ──
        log.info(f"Starting intraday scan for {len(symbols)} symbols...")
        scan_intraday(symbols)

        # ── SWING SCAN: once per day after 3:30 PM ──
        if (now.hour, now.minute) >= (15, 30) and _swing_scan_done_date != today:
            log.info("Starting daily swing scan...")
            scan_swing(symbols)
            _swing_scan_done_date = today
            log.info("Daily swing scan complete.")

        # Re-fetch universe if somehow empty
        if not symbols:
            symbols = get_liquid_universe()

        time.sleep(config.SCAN_INTERVAL_SEC)

if __name__ == "__main__":
    run()
