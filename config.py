import os
from dotenv import load_dotenv

load_dotenv()

API_KEY    = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in .env file")

PAPER      = True 

TOTAL_CAPITAL        = 50000.00
SWING_CAPITAL        = 25000.00
INTRADAY_CAPITAL     = 25000.00
MAX_DEPLOYED_CAPITAL = 50000.00

MAX_RISK_PER_TRADE   = 0.02
MAX_POSITION_SIZE    = 5000.00
MAX_OPEN_POSITIONS   = 10
MIN_RRR              = 2.0

# ── Timing Constants ──
EOD_CLOSE_TIME         = (15, 50)  # Close Day Trades
STALE_REAPER_TIME      = (15, 31)  # Check 15-day Swings
SWING_MAX_HOLD_DAYS    = 15
SCAN_INTERVAL_SEC      = 300
SWING_PASSING_SCORE    = 70
INTRADAY_PASSING_SCORE = 70