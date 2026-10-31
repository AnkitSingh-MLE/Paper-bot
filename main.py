"""
main.py — one trade a day. Opus picks the stock, code enforces every limit.

  python3 main.py entry [--force]   # ~9:45 AM ET: Opus reads news, picks ONE stock, buys (bracket order)
  python3 main.py exit              # ~3:45 PM ET: closes today's position, logs P&L

Mode comes from DAYBOT_MODE in .env:  paper (default)  |  live (real money)
"""
import os, sys, re, csv, json, math, time, logging
import urllib.request, urllib.error
from datetime import datetime, timedelta, timezone, time as dtime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"))

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (MarketOrderRequest, TakeProfitRequest,
                                     StopLossRequest, GetOrdersRequest)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame
from notify import alert_info, alert_error

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s daybot: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("daybot")

# ── SETTINGS ───────────────────────────────────────────────────────────────
ET = ZoneInfo("America/New_York")
LIVE = os.getenv("DAYBOT_MODE", "paper").strip().lower() == "live"
MODE = "LIVE" if LIVE else "PAPER"
BUDGET_USD = 5000.0 if LIVE else 10000.0     # live never exceeds the $5k you funded
STOP_PCT = 6.0                               # hard stop below entry (bracket order)
TARGET_PCT = 12.0                            # take-profit above entry (bracket order)
LOSS_LIMIT_USD = float(os.getenv("DAYBOT_LOSS_LIMIT", "5000"))  # halt if equity falls this far
MIN_PRICE = 5.0
MIN_IEX_DOLLAR_VOL = 1_000_000               # IEX shows only a slice of real volume; ~30x this is real
MODEL = os.getenv("DAYBOT_MODEL", "claude-opus-5-5")
USE_WEB_SEARCH = os.getenv("DAYBOT_WEB_SEARCH", "true").strip().lower() == "true"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET = os.getenv("ALPACA_SECRET_KEY")
STATE_FILE = os.path.join(BASE, "daybot_state.json")
TRADES_FILE = os.path.join(BASE, "daybot_trades.csv")
FIELDS = ["date", "mode", "symbol", "qty", "entry", "stop", "target", "confidence",
          "catalyst", "thesis", "exit_price", "pnl_usd", "pnl_pct", "status"]

if not API_KEY or not SECRET:
    raise SystemExit("ALPACA_API_KEY / ALPACA_SECRET_KEY missing in .env")

trading = TradingClient(API_KEY, SECRET, paper=not LIVE)
data = StockHistoricalDataClient(API_KEY, SECRET)


# ── SMALL HELPERS ──────────────────────────────────────────────────────────
def val(x):
    return getattr(x, "value", x)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def append_row(row):
    new = not os.path.isfile(TRADES_FILE)
    with open(TRADES_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def update_today_row(today, **changes):
    if not os.path.isfile(TRADES_FILE):
        return
    with open(TRADES_FILE, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in reversed(rows):
        if r["date"] == today:
            r.update(changes)
            break
    with open(TRADES_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


# ── MARKET CONTEXT (all from Alpaca, free) ─────────────────────────────────
def get_news(hours=18, limit=50):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"https://data.alpaca.markets/v1beta1/news?start={since}&limit={limit}&sort=desc"
    req = urllib.request.Request(url, headers={"APCA-API-KEY-ID": API_KEY,
                                               "APCA-API-SECRET-KEY": SECRET})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            items = json.loads(r.read()).get("news", [])
        lines = [f"- [{a.get('created_at','')[:16]}] {a.get('headline','')[:150]} "
                 f"({','.join(a.get('symbols', [])[:4])})" for a in items]
        return "\n".join(lines) or "no headlines"
    except Exception as e:
        log.warning(f"news fetch failed: {e}")
        return "news unavailable"


def get_movers():
    try:
        from alpaca.data.historical.screener import ScreenerClient
        from alpaca.data.requests import MarketMoversRequest
        m = ScreenerClient(API_KEY, SECRET).get_market_movers(MarketMoversRequest(top=15))
        return ", ".join(f"{g.symbol} {g.percent_change:+.1f}% ${g.price:.2f}" for g in m.gainers)
    except Exception as e:
        log.warning(f"movers fetch failed: {e}")
        return "unavailable"


# ── OPUS ───────────────────────────────────────────────────────────────────
SYSTEM = """You are the research analyst for an automated, long-only, one-stock-per-day \
intraday trading bot. Each morning you read the latest world and market news and pick the \
ONE US-listed stock most likely to rise the most between about 9:45 AM and 3:45 PM Eastern \
today. The bot buys in the morning and sells by 3:45 PM, so only today's price move matters.
Prefer a fresh, specific catalyst (earnings beat, guidance raise, upgrade, big contract, \
regulatory approval, sector-wide macro move, sympathy move), strong volume, liquid names.
Avoid OTC stocks, anything under $5, illiquid names, and stocks that already ran 15%+ with \
no further catalyst. Never pick something you cannot tie to a concrete reason.
If you have a web search tool, use it (a few searches) for overnight world news, pre-market \
movers and catalysts for your top candidates.
A separate risk manager sets size and stops; you only choose the stock.
Your FINAL message must be ONLY this JSON, no markdown fences, no other text:
{"ticker": "XXXX", "alternates": ["YYYY", "ZZZZ"], "catalyst": "short", \
"thesis": "one or two sentences", "expected_move_pct": 0.0, "confidence": 0.0, \
"risk": "short"}"""


def _post(payload):
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "x-api-key": ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01"},
        method="POST")
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read())


def ask_opus(news, movers):
    now = datetime.now(ET)
    prompt = (f"Today is {now:%A %Y-%m-%d %H:%M} ET. The market just opened.\n\n"
              f"LATEST HEADLINES (Alpaca news, last 18h):\n{news}\n\n"
              f"TODAY'S TOP GAINERS SO FAR: {movers}\n\n"
              "Pick the single best long candidate for today and answer with the JSON only.")
    payload = {"model": MODEL, "max_tokens": 2500, "system": SYSTEM,
               "messages": [{"role": "user", "content": prompt}]}
    if USE_WEB_SEARCH:
        payload["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
    try:
        body = _post(payload)
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:300]
        if USE_WEB_SEARCH and e.code == 400:
            log.warning(f"web search rejected ({err}); retrying without it")
            payload.pop("tools")
            body = _post(payload)
        else:
            raise RuntimeError(f"Anthropic HTTP {e.code}: {err}")
    texts = [b["text"] for b in body.get("content", []) if b.get("type") == "text"]
    for t in reversed(texts):
        s, e = t.find("{"), t.rfind("}")
        if s != -1 and e > s:
            try:
                return json.loads(t[s:e + 1])
            except json.JSONDecodeError:
                continue
    raise RuntimeError("Opus returned no parseable JSON")


# ── VALIDATION (code never trusts the pick blindly) ────────────────────────
def validate(sym):
    sym = str(sym).strip().upper()
    if not re.fullmatch(r"[A-Z]{1,5}", sym):
        return sym, None, "bad_symbol"
    try:
        a = trading.get_asset(sym)
    except Exception:
        return sym, None, "unknown_symbol"
    if not a.tradable or str(val(a.status)).lower() != "active":
        return sym, None, "not_tradable"
    if "OTC" in str(val(a.exchange)).upper():
        return sym, None, "otc"
    try:
        price = float(data.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=sym, feed="iex"))[sym].price)
        end = datetime.now(timezone.utc) - timedelta(minutes=16)
        bars = data.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=sym, timeframe=TimeFrame.Day,
            start=end - timedelta(days=40), end=end, feed="iex")).df
    except Exception as e:
        return sym, None, f"data_error:{e}"
    if price < MIN_PRICE:
        return sym, None, f"price_{price:.2f}_below_{MIN_PRICE}"
    if bars.empty or (bars["close"] * bars["volume"]).tail(20).mean() < MIN_IEX_DOLLAR_VOL:
        return sym, None, "illiquid"
    return sym, price, "ok"


# ── ENTRY ──────────────────────────────────────────────────────────────────
def entry(force=False):
    now = datetime.now(ET)
    today = now.date().isoformat()
    if not trading.get_clock().is_open:
        log.info("Market closed — nothing to do.")
        return
    if not force and not (dtime(9, 35) <= now.time() <= dtime(11, 30)):
        log.info("Outside entry window (9:35–11:30 ET). Use --force to override.")
        return
    state = load_state()
    if state.get("date") == today and state.get("symbol"):
        log.info(f"Already traded {state['symbol']} today — skipping.")
        return
    if not ANTHROPIC_API_KEY:
        alert_error("DAYBOT: ANTHROPIC_API_KEY missing — no trade today.")
        return

    acct = trading.get_account()
    equity = float(acct.equity)
    base_key = f"start_equity_{MODE.lower()}"
    state.setdefault(base_key, equity)
    if equity <= state[base_key] - LOSS_LIMIT_USD:
        save_state(state)
        alert_error(f"DAYBOT HALTED [{MODE}]: equity ${equity:,.0f} is ${LOSS_LIMIT_USD:,.0f} "
                    f"below start ${state[base_key]:,.0f}. No more trades until you raise "
                    f"DAYBOT_LOSS_LIMIT or reset.")
        return

    pick = ask_opus(get_news(), get_movers())
    log.info(f"OPUS pick: {pick}")
    candidates = [pick.get("ticker")] + list(pick.get("alternates", []))[:3]

    chosen, price = None, None
    for c in candidates:
        if not c:
            continue
        sym, px, reason = validate(c)
        log.info(f"VALIDATE {sym}: {reason}")
        if px:
            chosen, price = sym, px
            break
    if not chosen:
        alert_info(f"DAYBOT [{MODE}]: Opus picked {candidates} but none passed validation. No trade today.")
        return

    budget = min(BUDGET_USD, float(acct.cash)) * 0.98
    qty = math.floor(budget / price)
    if qty < 1:
        alert_info(f"DAYBOT [{MODE}]: {chosen} @ ${price:.2f} too expensive for budget ${budget:,.0f}.")
        return

    stop = round(price * (1 - STOP_PCT / 100), 2)
    target = round(price * (1 + TARGET_PCT / 100), 2)
    order = trading.submit_order(MarketOrderRequest(
        symbol=chosen, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
        order_class="bracket",
        take_profit=TakeProfitRequest(limit_price=target),
        stop_loss=StopLossRequest(stop_price=stop)))
    time.sleep(4)
    try:
        filled = trading.get_order_by_id(order.id).filled_avg_price
        entry_px = float(filled) if filled else price
    except Exception:
        entry_px = price

    state.update({"date": today, "symbol": chosen, "qty": qty, "entry": entry_px})
    save_state(state)
    append_row({"date": today, "mode": MODE, "symbol": chosen, "qty": qty,
                "entry": round(entry_px, 2), "stop": stop, "target": target,
                "confidence": pick.get("confidence", ""), "catalyst": pick.get("catalyst", ""),
                "thesis": pick.get("thesis", ""), "status": "open"})
    alert_info(f"🟢 DAYBOT [{MODE}] BUY {chosen} x{qty} @ ${entry_px:.2f} "
               f"(${qty * entry_px:,.0f}) | stop ${stop} | target ${target} | "
               f"conf {pick.get('confidence')} | {pick.get('catalyst')} — {pick.get('thesis')}")


# ── EXIT ───────────────────────────────────────────────────────────────────
def _find_sell_fill(sym):
    orders = trading.get_orders(GetOrdersRequest(
        status=QueryOrderStatus.CLOSED, symbols=[sym], nested=True, limit=20,
        after=datetime.now(timezone.utc) - timedelta(days=1)))
    for o in orders:
        for x in [o] + list(o.legs or []):
            if "sell" in str(x.side).lower() and x.filled_avg_price:
                return float(x.filled_avg_price)
    return None


def exit_():
    today = datetime.now(ET).date().isoformat()
    state = load_state()
    sym = state.get("symbol") if state.get("date") == today else None
    if not sym:
        log.info("No daybot position for today — nothing to close.")
        return

    for o in trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[sym])):
        try:
            trading.cancel_order_by_id(o.id)
        except Exception:
            pass

    try:
        pos = trading.get_open_position(sym)
    except Exception:
        pos = None

    entry_px, qty = float(state.get("entry", 0)), int(state.get("qty", 0))
    if pos is not None:
        entry_px = float(pos.avg_entry_price)
        qty = int(float(pos.qty))
        o = trading.close_position(sym)
        time.sleep(5)
        fill = trading.get_order_by_id(o.id).filled_avg_price
        exit_px = float(fill) if fill else float(pos.current_price)
        status = "closed_eod"
    else:
        exit_px = _find_sell_fill(sym)
        status = "hit_stop_or_target" if exit_px else "no_position_found"

    if exit_px and entry_px:
        pnl = round((exit_px - entry_px) * qty, 2)
        pct = round((exit_px / entry_px - 1) * 100, 2)
        update_today_row(today, exit_price=round(exit_px, 2), pnl_usd=pnl, pnl_pct=pct, status=status)
        icon = "✅" if pnl >= 0 else "🔴"
        alert_info(f"{icon} DAYBOT [{MODE}] EXIT {sym} x{qty}: ${entry_px:.2f} → ${exit_px:.2f} "
                   f"| P&L ${pnl:+,.2f} ({pct:+.2f}%) | {status}")
    else:
        update_today_row(today, status=status)
        alert_info(f"⚠️ DAYBOT [{MODE}] EXIT {sym}: {status} — check Alpaca manually.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "entry":
            entry(force="--force" in sys.argv)
        elif cmd == "exit":
            exit_()
        else:
            print(__doc__)
    except Exception as e:
        log.exception("daybot failed")
        alert_error(f"DAYBOT [{MODE}] {cmd} FAILED: {e}")
        raise
