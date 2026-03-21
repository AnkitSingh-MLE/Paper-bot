"""
daily_report.py — Varsity Bot Daily Report
───────────────────────────────────────────
Run anytime to get a full snapshot of today's activity.

Usage:
    python daily_report.py          # Today's report
    python daily_report.py --all    # All-time summary
"""

import os
import sys
import csv
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()

SEP  = "=" * 55
SEP2 = "─" * 55

def section(title):
    print(f"\n{SEP2}")
    print(f"  {title}")
    print(SEP2)

# ── 1. Account snapshot from Alpaca ───────────────────────
section("ACCOUNT SNAPSHOT")
try:
    from alpaca.trading.client import TradingClient
    import config
    client = TradingClient(config.API_KEY, config.SECRET_KEY, paper=config.PAPER)
    acct   = client.get_account()

    equity       = float(acct.equity)
    cash         = float(acct.cash)
    buying_power = float(acct.buying_power)
    pnl_today    = float(acct.equity) - float(acct.last_equity)
    pnl_pct      = (pnl_today / float(acct.last_equity)) * 100 if float(acct.last_equity) else 0
    dt_count     = int(acct.daytrade_count)

    print(f"  Equity:        ${equity:>10,.2f}")
    print(f"  Cash:          ${cash:>10,.2f}")
    print(f"  Buying Power:  ${buying_power:>10,.2f}")
    arrow = "▲" if pnl_today >= 0 else "▼"
    print(f"  Today P&L:     {arrow} ${abs(pnl_today):>9,.2f}  ({pnl_pct:+.2f}%)")
    print(f"  Day Trades:    {dt_count}/3  (PDT limit)")
    print(f"  Mode:          {'PAPER' if config.PAPER else 'LIVE'}")

except Exception as e:
    print(f"  Could not fetch account: {e}")

# ── 2. Open positions ──────────────────────────────────────
section("OPEN POSITIONS")
try:
    positions = client.get_all_positions()
    if not positions:
        print("  No open positions")
    else:
        print(f"  {'Symbol':<8} {'Qty':>8} {'Entry':>10} {'Current':>10} {'P&L':>10} {'P&L%':>7}")
        print(f"  {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*10} {'-'*7}")
        total_pnl = 0
        for p in positions:
            qty        = float(p.qty)
            entry      = float(p.avg_entry_price)
            current    = float(p.current_price)
            unrealized = float(p.unrealized_pl)
            pnl_pct    = float(p.unrealized_plpc) * 100
            total_pnl += unrealized
            arrow = "▲" if unrealized >= 0 else "▼"
            print(f"  {p.symbol:<8} {qty:>8.4f} ${entry:>9.2f} ${current:>9.2f} "
                  f"{arrow}${abs(unrealized):>8.2f} {pnl_pct:>+6.2f}%")
        print(f"  {'':8} {'':8} {'':10} {'TOTAL':>10} "
              f"{'▲' if total_pnl>=0 else '▼'}${abs(total_pnl):>8.2f}")
except Exception as e:
    print(f"  Could not fetch positions: {e}")

# ── 3. Pending orders ──────────────────────────────────────
section("PENDING ORDERS (GTC Swing)")
try:
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
    if not orders:
        print("  No pending orders")
    else:
        print(f"  {'Symbol':<8} {'Side':<6} {'Type':<8} {'Limit':>10} {'Stop':>10} {'TP':>10}")
        print(f"  {'-'*8} {'-'*6} {'-'*8} {'-'*10} {'-'*10} {'-'*10}")
        for o in orders:
            limit = f"${float(o.limit_price):.2f}" if o.limit_price else "market"
            # Get stop and take profit from legs if bracket order
            stop_price = ""
            tp_price   = ""
            if o.legs:
                for leg in o.legs:
                    if "stop" in str(leg.order_type).lower():
                        stop_price = f"${float(leg.stop_price):.2f}" if leg.stop_price else ""
                    if "limit" in str(leg.order_type).lower() and leg != o:
                        tp_price = f"${float(leg.limit_price):.2f}" if leg.limit_price else ""
            print(f"  {o.symbol:<8} {str(o.side).replace('OrderSide.',''):<6} "
                  f"{str(o.time_in_force).replace('TimeInForce.',''):<8} "
                  f"{limit:>10} {stop_price:>10} {tp_price:>10}")
except Exception as e:
    print(f"  Could not fetch orders: {e}")

# ── 4. Today's trades from CSV ─────────────────────────────
section(f"TODAY'S LOGGED TRADES  ({date.today()})")
TRADES_FILE = os.path.join(os.path.dirname(__file__), "trades.csv")
today = date.today().isoformat()
show_all = "--all" in sys.argv

try:
    if not os.path.isfile(TRADES_FILE):
        print("  trades.csv not found — no trades logged yet")
    else:
        trades = []
        with open(TRADES_FILE, newline="") as f:
            for row in csv.DictReader(f):
                if show_all or row.get("date") == today:
                    trades.append(row)

        if not trades:
            print(f"  No trades {'logged' if show_all else 'today'}")
        else:
            label = "ALL TIME" if show_all else "TODAY"
            print(f"  Showing {len(trades)} {label.lower()} trade(s)\n")
            print(f"  {'Time':<10} {'Symbol':<8} {'Strategy':<16} {'Score':>5} "
                  f"{'Entry':>8} {'Stop':>8} {'Target':>8} {'RRR':>5} {'Result':<8}")
            print(f"  {'-'*10} {'-'*8} {'-'*16} {'-'*5} "
                  f"{'-'*8} {'-'*8} {'-'*8} {'-'*5} {'-'*8}")

            total_pnl = 0.0
            wins = losses = open_trades = 0
            for t in trades:
                time_str = t.get("timestamp","")[:10]
                pnl      = float(t["pnl"]) if t.get("pnl") else None
                result   = t.get("result","open")
                if pnl is not None:
                    total_pnl += pnl
                    if pnl > 0: wins += 1
                    else: losses += 1
                else:
                    open_trades += 1
                pnl_str = f"${pnl:+.2f}" if pnl is not None else "open"
                print(f"  {time_str:<10} {t['symbol']:<8} {t['strategy']:<16} "
                      f"{t.get('score','')!s:>5} "
                      f"${float(t['entry']):>7.2f} "
                      f"${float(t['stop']):>7.2f} "
                      f"${float(t['target']):>7.2f} "
                      f"{float(t.get('rrr',0)):>5.1f} "
                      f"{pnl_str:<8}")

            print(f"\n  {'─'*50}")
            print(f"  Closed trades:  {wins+losses}  "
                  f"(Wins: {wins}  Losses: {losses}  "
                  f"Win rate: {wins/(wins+losses)*100:.0f}%)" if wins+losses else
                  f"  Closed trades:  0")
            print(f"  Open trades:    {open_trades}")
            if wins + losses > 0:
                arrow = "▲" if total_pnl >= 0 else "▼"
                print(f"  Realized P&L:   {arrow} ${abs(total_pnl):.2f}")

except Exception as e:
    print(f"  Error reading trades: {e}")

# ── 5. Recent bot activity from log ───────────────────────
section("RECENT BOT ACTIVITY (last 10 events)")
LOG_FILE = os.path.join(os.path.dirname(__file__), "bot.log")
try:
    if not os.path.isfile(LOG_FILE):
        print("  bot.log not found")
    else:
        with open(LOG_FILE) as f:
            lines = f.readlines()
        # Filter meaningful lines only
        keywords = ["SWING", "INTRADAY", "ORDER", "KILL", "STALE",
                    "scan complete", "market open", "ERROR", "WARNING"]
        meaningful = [l.strip() for l in lines
                      if any(k.lower() in l.lower() for k in keywords)]
        recent = meaningful[-10:] if len(meaningful) >= 10 else meaningful
        if not recent:
            print("  No significant events yet — waiting for market open")
        else:
            for line in recent:
                print(f"  {line}")
except Exception as e:
    print(f"  Could not read log: {e}")

# ── Footer ─────────────────────────────────────────────────
print(f"\n{SEP}")
print(f"  Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
print(f"  Run 'python daily_report.py --all' for all-time trade history")
print(SEP)
