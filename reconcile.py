"""
reconcile.py
────────────
Runs daily at 4:05 PM ET (after market close).
Pulls all filled orders from Alpaca for today,
matches them to open rows in trades.csv,
and writes back result (win/loss) and pnl_pct.

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

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
CSV_PATH  = os.path.join(BASE_DIR, "trades.csv")


def get_todays_filled_orders() -> list[dict]:
    """Fetch all filled orders from Alpaca for today."""
    today_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        orders = trading_client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            after=today_utc,
            limit=200,
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
            "side":         o.side,
            "filled_price": float(o.filled_avg_price),
            "filled_qty":   float(o.filled_qty or 0),
            "filled_at":    o.filled_at,
            "order_type":   str(o.order_type),
        })
    log.info(f"Fetched {len(filled)} filled orders from Alpaca today.")
    return filled


def reconcile():
    if not os.path.exists(CSV_PATH):
        log.warning(f"trades.csv not found at {CSV_PATH} — nothing to reconcile.")
        return

    df = pd.read_csv(CSV_PATH)

    # Ensure required columns exist
    for col in ["result", "pnl_pct", "exit_price"]:
        if col not in df.columns:
            df[col] = None

    open_mask = df["result"].isna() | (df["result"] == "open")
    open_trades = df[open_mask].copy()

    if open_trades.empty:
        log.info("No open trades to reconcile.")
        return

    log.info(f"Found {len(open_trades)} open trade rows to reconcile.")

    filled_orders = get_todays_filled_orders()
    if not filled_orders:
        log.warning("No filled orders from Alpaca — nothing to match.")
        return

    # Build a lookup: symbol -> list of exit fills (SELL for longs, BUY for shorts)
    exit_fills: dict[str, list[dict]] = {}
    for o in filled_orders:
        sym = o["symbol"]
        # Exit fill = SELL for long trades, BUY for short trades
        if o["side"] in (OrderSide.SELL, "sell", "OrderSide.SELL"):
            exit_fills.setdefault(sym, []).append(o)
        elif o["side"] in (OrderSide.BUY, "buy", "OrderSide.BUY"):
            # Could be closing a short
            exit_fills.setdefault(sym + "_short", []).append(o)

    matched   = 0
    unmatched = 0

    for idx, row in open_trades.iterrows():
        sym      = row["symbol"]
        strategy = str(row.get("strategy", ""))
        is_short = "short" in strategy

        lookup_key = sym + "_short" if is_short else sym
        exits = exit_fills.get(lookup_key, [])

        if not exits:
            log.info(f"NO MATCH: {sym} ({strategy}) — no exit fill found today.")
            unmatched += 1
            continue

        # Use the last exit fill for this symbol
        exit_fill  = exits[-1]
        exit_price = exit_fill["filled_price"]
        entry_price = float(row.get("entry_price", row.get("entry", 0)))

        if entry_price == 0:
            log.warning(f"SKIP {sym}: entry_price is 0 — cannot calculate P&L.")
            continue

        if is_short:
            pnl_pct = (entry_price - exit_price) / entry_price
        else:
            pnl_pct = (exit_price - entry_price) / entry_price

        result = "win" if pnl_pct > 0 else "loss"

        df.at[idx, "result"]      = result
        df.at[idx, "pnl_pct"]     = round(pnl_pct * 100, 4)  # store as percentage
        df.at[idx, "exit_price"]  = exit_price

        log.info(
            f"MATCHED: {sym} | {strategy} | entry=${entry_price:.2f} "
            f"exit=${exit_price:.2f} | pnl={pnl_pct*100:.2f}% | {result.upper()}"
        )
        matched += 1

    df.to_csv(CSV_PATH, index=False)

    # Summary
    wins   = df[df["result"] == "win"]
    losses = df[df["result"] == "loss"]
    total  = len(wins) + len(losses)
    win_rate = (len(wins) / total * 100) if total > 0 else 0

    log.info("─── RECONCILE SUMMARY ───────────────────────────")
    log.info(f"  Matched today:  {matched}  |  Unmatched: {unmatched}")
    log.info(f"  All-time wins:  {len(wins)}  |  Losses: {len(losses)}")
    log.info(f"  All-time win rate: {win_rate:.1f}%")
    if total > 0:
        avg_win  = wins["pnl_pct"].mean() if not wins.empty else 0
        avg_loss = losses["pnl_pct"].mean() if not losses.empty else 0
        log.info(f"  Avg win: {avg_win:.2f}%  |  Avg loss: {avg_loss:.2f}%")
    log.info("─────────────────────────────────────────────────")


if __name__ == "__main__":
    reconcile()
