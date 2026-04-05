"""
reconcile.py
────────────
Runs daily at 4:05 PM ET (after market close).
Pulls filled orders from Alpaca (last 30 days),
matches them to open rows in trades.csv,
and writes back result (win/loss) and pnl.

Run manually:  python3 reconcile.py
Cron:          5 20 * * 1-5  (8:05 PM UTC = 4:05 PM ET)
"""

import os
import logging
import pandas as pd
from datetime import datetime, timezone, timedelta
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus, OrderSide

import config
from broker import trading_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s reconcile: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("reconcile")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "trades.csv")

# Look back 30 days to catch any stale unreconciled trades
LOOKBACK_DAYS = 30


def get_filled_orders() -> list[dict]:
    """Fetch all filled orders from Alpaca for the last LOOKBACK_DAYS days."""
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    try:
        orders = trading_client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            after=since,
            limit=500,
        ))
    except Exception as e:
        log.error(f"Failed to fetch orders from Alpaca: {e}")
        return []

    filled = []
    for o in orders:
        if o.filled_avg_price is None:
            continue
        filled.append({
            "symbol":       o.symbol,
            "side":         str(o.side),
            "filled_price": float(o.filled_avg_price),
            "filled_qty":   float(o.filled_qty or 0),
            "filled_at":    o.filled_at,
        })

    log.info(f"Fetched {len(filled)} filled orders from Alpaca (last {LOOKBACK_DAYS} days).")
    return filled


def reconcile():
    if not os.path.exists(CSV_PATH):
        log.warning(f"trades.csv not found at {CSV_PATH} — nothing to reconcile.")
        return

    df = pd.read_csv(CSV_PATH)

    # Ensure exit_price column exists
    if "exit_price" not in df.columns:
        df["exit_price"] = None

    open_mask   = df["result"].isna() | (df["result"] == "open")
    open_trades = df[open_mask].copy()

    if open_trades.empty:
        log.info("No open trades to reconcile.")
        _print_summary(df)
        return

    log.info(f"Found {len(open_trades)} open trade rows to reconcile.")

    filled_orders = get_filled_orders()
    if not filled_orders:
        log.warning("No filled orders from Alpaca — nothing to match.")
        return

    # Build lookup: symbol -> list of exit fills
    # Exit for long  = SELL side fill
    # Exit for short = BUY side fill
    long_exits:  dict[str, list[dict]] = {}
    short_exits: dict[str, list[dict]] = {}

    for o in filled_orders:
        sym  = o["symbol"]
        side = o["side"].lower()
        if "sell" in side:
            long_exits.setdefault(sym, []).append(o)
        elif "buy" in side:
            short_exits.setdefault(sym, []).append(o)

    matched   = 0
    unmatched = 0

    for idx, row in open_trades.iterrows():
        sym       = row["symbol"]
        direction = str(row.get("direction", "long")).lower()
        is_short  = direction == "short"
        entry     = float(row.get("entry", 0))

        exits = short_exits.get(sym, []) if is_short else long_exits.get(sym, [])

        if not exits:
            log.info(f"NO MATCH: {sym} ({direction}) — no exit fill found in last {LOOKBACK_DAYS} days.")
            unmatched += 1
            continue

        # Use the most recent exit fill
        exit_fill  = sorted(exits, key=lambda x: x["filled_at"])[-1]
        exit_price = exit_fill["filled_price"]

        if entry == 0:
            log.warning(f"SKIP {sym}: entry is 0 — cannot calculate P&L.")
            continue

        if is_short:
            pnl = round((entry - exit_price) / entry * 100, 4)
        else:
            pnl = round((exit_price - entry) / entry * 100, 4)

        result = "win" if pnl > 0 else "loss"

        df.at[idx, "result"]     = result
        df.at[idx, "pnl"]        = pnl
        df.at[idx, "exit_price"] = exit_price

        log.info(
            f"MATCHED: {sym} | {direction} | entry=${entry:.2f} "
            f"exit=${exit_price:.2f} | pnl={pnl:.2f}% | {result.upper()}"
        )
        matched += 1

    df.to_csv(CSV_PATH, index=False)
    log.info(f"trades.csv updated — {matched} matched, {unmatched} unmatched.")
    _print_summary(df)


def _print_summary(df: pd.DataFrame):
    wins   = df[df["result"] == "win"]
    losses = df[df["result"] == "loss"]
    total  = len(wins) + len(losses)
    win_rate = (len(wins) / total * 100) if total > 0 else 0

    log.info("─── RECONCILE SUMMARY ───────────────────────────")
    log.info(f"  Total closed trades: {total}  (wins: {len(wins)} | losses: {len(losses)})")
    log.info(f"  Win rate: {win_rate:.1f}%")
    if not wins.empty:
        log.info(f"  Avg win:  {wins['pnl'].mean():.2f}%")
    if not losses.empty:
        log.info(f"  Avg loss: {losses['pnl'].mean():.2f}%")
    log.info(f"  Still open: {len(df[df['result'] == 'open'])}")
    log.info("─────────────────────────────────────────────────")


if __name__ == "__main__":
    reconcile()
