import datetime
import time
import logging
from broker import is_market_open, force_close_intraday, close_stale_swing_trades
import config
from universe import get_liquid_universe
from scanner import scan_swing, scan_intraday # Ensure these exist

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("main")

def run():
    log.info(f"STARTING PAPER BOT: $25k Swing / $25k Day")
    while True:
        if not is_market_open():
            time.sleep(60)
            continue

        now = datetime.datetime.now().time()
        
        # ── JANITOR CHECKS ──
        if (now.hour, now.minute) == config.STALE_REAPER_TIME:
            close_stale_swing_trades()
        if (now.hour, now.minute) == config.EOD_CLOSE_TIME:
            force_close_intraday()

        # ── SCANS ──
        symbols = get_liquid_universe()
        scan_intraday(symbols)
        if now.hour == 15 and now.minute >= 30:
            scan_swing(symbols)
        
        time.sleep(config.SCAN_INTERVAL_SEC)

if __name__ == "__main__":
    run()