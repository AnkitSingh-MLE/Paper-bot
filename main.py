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


def _time_is(hour: int, minute: int) -> bool:
    now = datetime.datetime.now()
    return now.hour == hour and now.minute == minute


def run():
    global _swing_scan_done_date
    log.info("STARTING PAPER BOT: $25k Swing / $25k Day (GCP micro build)")

    symbols = get_liquid_universe()
    log.info(f"Universe loaded: {len(symbols)} symbols")

    while True:
        if not is_market_open():
            log.info("Market is closed. Sleeping 60s...")
            time.sleep(60)        # Poll once per minute while closed — very cheap
            continue

        now  = datetime.datetime.now()
        today = now.date()

        # ── JANITOR: stale swing positions at 3:31 PM ──
        if _time_is(*config.STALE_REAPER_TIME):
            close_stale_swing_trades()

        # ── JANITOR: force-close intraday at 3:50 PM ──
        if _time_is(*config.EOD_CLOSE_TIME):
            force_close_intraday()

        # ── INTRADAY SCAN: every cycle while market is open ──
        log.info(f"Starting intraday scan for {len(symbols)} symbols...")
        scan_intraday(symbols)

        # ── SWING SCAN: once per day after 3:30 PM ──
        if (now.hour, now.minute) >= (15, 30) and _swing_scan_done_date != today:
            log.info("Starting daily swing scan...")
            scan_swing(symbols)
            _swing_scan_done_date = today
            log.info("Daily swing scan complete.")

        # ── Refresh universe once a month (handled inside get_liquid_universe cache) ──
        # Re-fetch only if the list somehow became empty
        if not symbols:
            symbols = get_liquid_universe()

        time.sleep(config.SCAN_INTERVAL_SEC)


if __name__ == "__main__":
    run()
