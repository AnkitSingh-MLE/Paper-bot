import logging
import data_fetcher
import indicators
import checklist
import pandas as pd

# Setup minimal logging to console
logging.basicConfig(level=logging.INFO)
print("\n=== STARTING SIGNAL DEBUG TEST ===\n")

symbol = "AAPL"

# 1. Test Data Fetcher
print(f"[*] Testing Data Fetcher for {symbol}...")
df = data_fetcher.get_intraday_bars(symbol)

if df is None or df.empty:
    print(f"[!] FAIL: data_fetcher returned NOTHING for {symbol}. Check Alpaca Keys/Feed.")
else:
    print(f"[+] SUCCESS: Fetched {len(df)} rows of data.")
    
    # 2. Test Indicators
    print(f"[*] Testing Indicators for {symbol}...")
    df_with_inds = indicators.calculate_intraday_indicators(df)
    
    if df_with_inds is None or df_with_inds.empty:
        print("[!] FAIL: Indicators returned empty. Usually means < 20 bars of data.")
    else:
        latest = df_with_inds.iloc[-1].to_dict()
        print(f"[+] SUCCESS: Indicators calculated. Latest RSI: {latest.get('rsi'):.2f}, VWAP: {latest.get('vwap'):.2f}")
        
        # 3. Test Scoring (Long)
        print(f"[*] Testing Scoring Logic for {symbol}...")
        passed, score, notes, breakdown = checklist.score_intraday_long(latest)
        
        print(f"\n--- RESULTS FOR {symbol} ---")
        print(f"PASSED FILTER: {passed}")
        print(f"SCORE:         {score}")
        print(f"NOTES:         {notes}")
        print(f"BREAKDOWN:     {breakdown}")

print("\n=== DEBUG TEST COMPLETE ===\n")
