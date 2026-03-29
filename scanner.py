import logging
import data_fetcher
import indicators
import checklist
import execution
import logger

log = logging.getLogger(__name__)

def scan_swing(symbols, place_orders=True):
    """Processes symbols for 2-3 week swing trades."""
    count = 0
    for sym in symbols:
        df = data_fetcher.get_daily_bars(sym)
        
        # Calculate indicators and return None if data is insufficient
        df = indicators.calculate_swing_indicators(df)
        
        # --- FIX: Safety check before using .iloc ---
        if df is None or df.empty:
            log.warning(f"Skipping {sym}: Insufficient historical data for indicators.")
            continue
            
        latest = df.iloc[-1].to_dict()
        
        # Apply the Hard Filters (EMA 200, ADX > 20)
        passed, score, notes, breakdown = checklist.score_varsity_swing_long(latest)
        
        if passed:
            log.info(f"SIGNAL: {sym} passed filters with score {score}")
            if place_orders:
                execution.execute_swing_trade(sym, latest)
            count += 1
            
    return count

def scan_intraday(symbols):
    """Placeholder for intraday scanning logic."""
    pass
