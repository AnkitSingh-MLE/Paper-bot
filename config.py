import os
from dotenv import load_dotenv

load_dotenv()

# ── API Credentials ────────────────────────────────────────────────────────────
API_KEY    = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
PAPER      = os.getenv("PAPER_TRADING", "true").lower() == "true"  # MUST BE TRUE

# ── Capital Allocation ─────────────────────────────────────────────────────────
TOTAL_CAPITAL        = 100_000.00
SWING_CAPITAL        = TOTAL_CAPITAL * 0.60    # $60k for swing
INTRADAY_CAPITAL     = TOTAL_CAPITAL * 0.40    # $40k for intraday
MAX_DEPLOYED_CAPITAL = 10_000.00               # Max total deployed at once

# ── Risk Management ────────────────────────────────────────────────────────────
MAX_RISK_PER_TRADE   = 0.02
MAX_POSITION_SIZE    = 3_000.00
MAX_OPEN_POSITIONS   = 9
DAILY_LOSS_LIMIT     = 0.03
MIN_RRR              = 1.5

# ── Swing Config ───────────────────────────────────────────────────────────────
SWING_SCAN_TIMES = [
    (11, 30),   # Scan only — no orders
    (13, 30),   # Scan only — no orders
    (15, 30),   # EOD — orders placed here only
]
SWING_MAX_HOLD_DAYS  = 15
SWING_PASSING_SCORE  = 70

# ── Intraday Config ────────────────────────────────────────────────────────────
INTRADAY_ENABLED       = True
INTRADAY_START_TIME    = (10, 31)
EOD_CLOSE_TIME         = (15, 50)
SCAN_INTERVAL_SEC      = 300
INTRADAY_PASSING_SCORE = 70
MAX_INTRADAY_TRADES    = 5       # Max 5 per day (long + short combined)

# ── Intraday Position Sizing ───────────────────────────────────────────────────
INTRADAY_BASE_SIZE   = 1_000.00  # $1000 at score 70
INTRADAY_SIZE_STEP   = 200.00    # +$200 per 10 points above 70
INTRADAY_MAX_SIZE    = 3_000.00  # Hard cap

# ── Short Selling ──────────────────────────────────────────────────────────────
ENABLE_SHORT_SELLING = True      # Paper account — enabled

# ── Filter Thresholds ──────────────────────────────────────────────────────────
VIX_MAX          = 35
MIN_PRICE        = 5.00
MIN_AVG_VOLUME   = 200_000
UNIVERSE_SIZE    = 100

# ── GTC & Log Settings ────────────────────────────────────────────────────────
GTC_MAX_DAYS     = 3
LOG_MAX_BYTES    = 5_000_000
LOG_BACKUP_COUNT = 3
